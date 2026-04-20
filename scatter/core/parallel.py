"""Multiprocessing infrastructure for Scatter — workers and orchestrators."""

import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple, Dict
from concurrent.futures import ProcessPoolExecutor, as_completed

from scatter.core.models import DEFAULT_MAX_WORKERS, DEFAULT_CHUNK_SIZE, MULTIPROCESSING_ENABLED


# --- multiprocessing utilities ---
def chunk_list(items: List, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[List]:
    """Split a list into chunks of specified size."""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def find_files_with_pattern_chunk(args: Tuple[Path, str, List[Path]]) -> List[Path]:
    """Worker function to find files matching a pattern in a list of directories."""
    base_path, pattern, dirs_chunk = args
    results = []
    for directory in dirs_chunk:
        try:
            if directory.is_dir():
                results.extend(list(directory.rglob(pattern)))
        except (OSError, PermissionError) as e:
            logging.debug(f"Error scanning directory {directory}: {e}")
    return results


def map_cs_to_projects_batch(args: Tuple[List[str]]) -> Dict[str, Optional[str]]:
    """
    Worker function to map a batch of .cs files to their parent .csproj files.

    Walks upward from each file's directory, caching directory-to-csproj results
    so multiple .cs files in the same project resolve without redundant filesystem walks.

    Args:
        args: Tuple containing:
            - cs_file_paths: List of .cs file absolute paths as strings

    Returns:
        Dictionary mapping str(cs_file_path) to str(csproj_path) or None
    """
    (cs_file_paths,) = args
    results = {}
    dir_to_csproj: Dict[
        str, Optional[str]
    ] = {}  # Cache: str(directory) -> Optional[str(csproj_path)]

    for cs_file_str in cs_file_paths:
        try:
            cs_file = Path(cs_file_str)
            current_path = cs_file.parent

            found_csproj = None
            dirs_walked = []

            while True:
                dir_key = str(current_path)

                if dir_key in dir_to_csproj:
                    found_csproj = dir_to_csproj[dir_key]
                    break

                dirs_walked.append(dir_key)

                try:
                    csproj_files = list(current_path.glob("*.csproj"))
                    if csproj_files:
                        found_csproj = str(csproj_files[0].resolve())
                        break
                except Exception as e:
                    logging.warning(
                        f"Error searching for .csproj in '{current_path}' for '{cs_file.name}': {e}"
                    )
                    break

                if current_path == current_path.parent:
                    break
                current_path = current_path.parent

            # Cache all walked directories with the result
            for d in dirs_walked:
                dir_to_csproj[d] = found_csproj

            results[cs_file_str] = found_csproj

        except Exception as e:
            logging.warning(f"Error mapping .cs file '{cs_file_str}' to project: {e}")
            results[cs_file_str] = None

    return results


def parse_csproj_files_batch(args: Tuple[List[Path], Path]) -> Dict[str, Dict]:
    """
    Worker function to parse a batch of .csproj files and check for ProjectReference to target.

    Args:
        args: Tuple containing:
            - csproj_batch: List of .csproj file paths to check
            - target_csproj_path: Path to the target .csproj file

    Returns:
        Dictionary mapping str(csproj_path) to results:
        {
            'is_consumer': bool,
            'consumer_name': str,
            'error': str or None
        }
    """
    csproj_batch, target_csproj_path = args
    results = {}
    consumer_namespaces = {"msb": "http://schemas.microsoft.com/developer/msbuild/2003"}

    for consumer_csproj_abs in csproj_batch:
        file_result = {
            "is_consumer": False,
            "consumer_name": consumer_csproj_abs.stem,
            "error": None,
        }

        try:
            tree = ET.parse(consumer_csproj_abs)
            root = tree.getroot()
            refs = root.findall(".//msb:ProjectReference", consumer_namespaces)
            if not refs:
                refs = root.findall(".//ProjectReference")

            for ref in refs:
                include_ = ref.get("Include")
                if include_:
                    # normalize paths so we can run on windows and *nix
                    include_ = include_.replace("\\", "/")

                    # ignore stuff that might not be built yet
                    if "$(" in include_ and ")" in include_:
                        logging.debug(
                            f"  Skipping ProjectReference with likely MSBuild property: '{include_}'"
                        )
                        continue

                    try:
                        ref_path_abs = (consumer_csproj_abs.parent / include_).resolve(strict=False)

                        if (
                            ref_path_abs.exists()
                            and target_csproj_path.exists()
                            and ref_path_abs.samefile(target_csproj_path)
                        ):
                            file_result["is_consumer"] = True
                            logging.debug(
                                f"  MATCH: Found direct reference from {consumer_csproj_abs.name}"
                            )
                            break
                    except OSError as e:
                        logging.warning(
                            f"Could not resolve or compare reference path '{include_}' in {consumer_csproj_abs.name}: {e}. Skipping reference."
                        )
                    except Exception as e:
                        logging.warning(
                            f"Error processing reference path '{include_}' in {consumer_csproj_abs.name}: {e}. Skipping reference."
                        )

        except (ET.ParseError, OSError) as e:
            file_result["error"] = f"{type(e).__name__} - {e}"
            logging.warning(
                f"Skipping reference check for {consumer_csproj_abs.name}: {file_result['error']}"
            )
        except Exception as e:
            file_result["error"] = f"Unexpected error: {e}"
            logging.warning(
                f"Unexpected error checking references in {consumer_csproj_abs.name}: {e}"
            )

        # Use string key for cross-process serialization
        results[str(consumer_csproj_abs)] = file_result

    return results


def parse_csproj_files_parallel(
    csproj_files: List[Path],
    target_csproj_path: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    csproj_analysis_chunk_size: int = 25,
    disable_multiprocessing: bool = False,
) -> Dict[str, Dict]:
    """
    Parse .csproj files in parallel to check for ProjectReference to target.

    Args:
        csproj_files: List of .csproj file paths to check
        target_csproj_path: Path to the target .csproj file
        max_workers: Maximum number of worker processes
        csproj_analysis_chunk_size: Number of files per worker batch
        disable_multiprocessing: Force sequential processing

    Returns:
        Dictionary mapping str(csproj_path) to parse results
    """
    # Force sequential if disabled or few files
    if (
        disable_multiprocessing
        or not MULTIPROCESSING_ENABLED
        or len(csproj_files) < csproj_analysis_chunk_size
    ):
        logging.debug(f"Using sequential csproj parsing for {len(csproj_files)} files")
        return parse_csproj_files_batch((csproj_files, target_csproj_path))

    logging.debug(
        f"Using parallel csproj parsing for {len(csproj_files)} files with {max_workers} workers"
    )

    try:
        file_chunks = chunk_list(csproj_files, csproj_analysis_chunk_size)
        all_results = {}
        completed_chunks = 0

        # Adaptive worker scaling based on file count
        if len(csproj_files) < 200:
            scaled_workers = min(max_workers, 4)
        elif len(csproj_files) < 1000:
            scaled_workers = min(max_workers, 8)
        else:
            scaled_workers = max_workers

        logging.debug(f"Processing {len(file_chunks)} csproj chunks with {scaled_workers} workers")

        with ProcessPoolExecutor(max_workers=scaled_workers) as executor:
            future_to_chunk = {
                executor.submit(parse_csproj_files_batch, (chunk, target_csproj_path)): chunk
                for chunk in file_chunks
            }

            for future in as_completed(future_to_chunk):
                try:
                    chunk_results = future.result(timeout=300)
                    all_results.update(chunk_results)
                    completed_chunks += 1

                    if completed_chunks % 5 == 0 or completed_chunks == len(file_chunks):
                        logging.debug(
                            f"csproj parsing progress: {completed_chunks}/{len(file_chunks)} chunks completed"
                        )

                except Exception as e:
                    logging.warning(f"Error processing csproj parsing chunk: {e}")
                    completed_chunks += 1

        logging.debug(f"Parallel csproj parsing completed: {len(all_results)} files analyzed")
        return all_results

    except Exception as e:
        logging.warning(f"Parallel csproj parsing failed: {e}. Falling back to sequential.")
        return parse_csproj_files_batch((csproj_files, target_csproj_path))


def map_cs_to_projects_parallel(
    cs_files: List[Path],
    max_workers: int = DEFAULT_MAX_WORKERS,
    cs_analysis_chunk_size: int = 50,
    disable_multiprocessing: bool = False,
) -> Dict[str, Optional[str]]:
    """
    Map .cs files to their parent .csproj files in parallel.

    Args:
        cs_files: List of .cs file paths to map
        max_workers: Maximum number of worker processes
        cs_analysis_chunk_size: Number of files per worker batch
        disable_multiprocessing: Force sequential processing

    Returns:
        Dictionary mapping str(cs_file_path) to str(csproj_path) or None
    """
    cs_file_strs = [str(f) for f in cs_files]

    # Force sequential if disabled or few files
    if (
        disable_multiprocessing
        or not MULTIPROCESSING_ENABLED
        or len(cs_files) < cs_analysis_chunk_size
    ):
        logging.debug(f"Using sequential project mapping for {len(cs_files)} files")
        return map_cs_to_projects_batch((cs_file_strs,))

    logging.debug(
        f"Using parallel project mapping for {len(cs_files)} files with {max_workers} workers"
    )

    try:
        file_chunks = chunk_list(cs_file_strs, cs_analysis_chunk_size)
        all_results = {}
        completed_chunks = 0

        # Adaptive worker scaling based on file count
        if len(cs_files) < 200:
            scaled_workers = min(max_workers, 4)
        elif len(cs_files) < 1000:
            scaled_workers = min(max_workers, 8)
        else:
            scaled_workers = max_workers

        logging.debug(
            f"Processing {len(file_chunks)} project mapping chunks with {scaled_workers} workers"
        )

        with ProcessPoolExecutor(max_workers=scaled_workers) as executor:
            future_to_chunk = {
                executor.submit(map_cs_to_projects_batch, (chunk,)): chunk for chunk in file_chunks
            }

            for future in as_completed(future_to_chunk):
                try:
                    chunk_results = future.result(timeout=300)
                    all_results.update(chunk_results)
                    completed_chunks += 1

                    if completed_chunks % 5 == 0 or completed_chunks == len(file_chunks):
                        logging.debug(
                            f"Project mapping progress: {completed_chunks}/{len(file_chunks)} chunks completed"
                        )

                except Exception as e:
                    logging.warning(f"Error processing project mapping chunk: {e}")
                    completed_chunks += 1

        logging.debug(f"Parallel project mapping completed: {len(all_results)} files mapped")
        return all_results

    except Exception as e:
        logging.warning(f"Parallel project mapping failed: {e}. Falling back to sequential.")
        return map_cs_to_projects_batch((cs_file_strs,))


def analyze_cs_files_batch(args: Tuple[List[Path], Dict[str, Any]]) -> Dict[Path, Dict[str, Any]]:
    """
    Worker function to analyze a batch of .cs files for various patterns.

    Args:
        args: Tuple containing:
            - files_batch: List of .cs file paths to analyze
            - analysis_config: Dictionary containing:
                - 'analysis_type': 'namespace', 'class', 'sproc', or 'method'
                - 'target_namespace': For namespace analysis
                - 'class_name': For class usage analysis
                - 'method_pattern': Compiled regex pattern for method analysis
                - 'sproc_pattern': Compiled regex pattern for sproc analysis
                - 'using_pattern': Compiled regex pattern for namespace analysis
                - 'class_pattern': Compiled regex pattern for class analysis

    Returns:
        Dictionary mapping file paths to analysis results:
        {
            file_path: {
                'matches': List of match objects or boolean,
                'has_match': boolean,
                'error': str or None,
                'content_preview': str (first 200 chars for debugging)
            }
        }
    """
    files_batch, analysis_config = args
    results = {}
    analysis_type = analysis_config.get("analysis_type", "unknown")

    for cs_file_path in files_batch:
        file_result = {"matches": [], "has_match": False, "error": None, "content_preview": ""}

        try:
            # Read file content
            content = cs_file_path.read_text(encoding="utf-8", errors="ignore")
            file_result["content_preview"] = content[:200].replace("\n", " ")

            # Perform analysis based on type
            if analysis_type == "namespace":
                using_pattern = analysis_config.get("using_pattern")
                if using_pattern:
                    matches = list(using_pattern.finditer(content))
                    file_result["matches"] = [match.group() for match in matches]
                    file_result["has_match"] = len(matches) > 0

            elif analysis_type == "class":
                class_pattern = analysis_config.get("class_pattern")
                if class_pattern:
                    matches = list(class_pattern.finditer(content))
                    file_result["matches"] = [match.group() for match in matches]
                    file_result["has_match"] = len(matches) > 0
                    # AST confirmation: filter false positives in comments/strings
                    if file_result["has_match"] and analysis_config.get("use_ast"):
                        from scatter.parsers.ast_validator import validate_type_usage

                        class_name = analysis_config.get("class_name", "")
                        if not validate_type_usage(content, class_name):
                            file_result["has_match"] = False
                            file_result["matches"] = []

            elif analysis_type == "sproc":
                sproc_pattern = analysis_config.get("sproc_pattern")
                if sproc_pattern:
                    matches = list(sproc_pattern.finditer(content))
                    file_result["matches"] = [(match.group(), match.start()) for match in matches]
                    file_result["has_match"] = len(matches) > 0

            elif analysis_type == "method":
                method_pattern = analysis_config.get("method_pattern")
                if method_pattern:
                    matches = list(method_pattern.finditer(content))
                    file_result["matches"] = [match.group() for match in matches]
                    file_result["has_match"] = len(matches) > 0
                    # AST confirmation: filter false positives in comments/strings
                    if file_result["has_match"] and analysis_config.get("use_ast"):
                        from scatter.parsers.ast_validator import validate_type_usage

                        method_name = analysis_config.get("method_name", "")
                        if method_name and not validate_type_usage(content, f".{method_name}"):
                            file_result["has_match"] = False
                            file_result["matches"] = []

            else:
                file_result["error"] = f"Unknown analysis type: {analysis_type}"

        except (OSError, UnicodeDecodeError) as e:
            file_result["error"] = f"File read error: {str(e)}"
        except Exception as e:
            file_result["error"] = f"Analysis error: {str(e)}"

        results[cs_file_path] = file_result

    return results


def analyze_cs_files_parallel(
    cs_files: List[Path],
    analysis_config: Dict[str, Any],
    max_workers: int = DEFAULT_MAX_WORKERS,
    cs_analysis_chunk_size: int = 50,
    disable_multiprocessing: bool = False,
) -> Dict[Path, Dict[str, Any]]:
    """
    Analyze a list of .cs files in parallel for specific patterns.

    Args:
        cs_files: List of .cs file paths to analyze
        analysis_config: Configuration for analysis (patterns, type, etc.)
        max_workers: Maximum number of worker processes
        cs_analysis_chunk_size: Number of files per worker batch
        disable_multiprocessing: Force sequential processing

    Returns:
        Dictionary mapping file paths to analysis results
    """
    analysis_type = analysis_config.get("analysis_type", "unknown")

    # Force sequential if disabled or few files
    if (
        disable_multiprocessing
        or not MULTIPROCESSING_ENABLED
        or len(cs_files) < cs_analysis_chunk_size
    ):
        logging.debug(f"Using sequential {analysis_type} analysis for {len(cs_files)} files")
        # Process all files in a single batch
        return analyze_cs_files_batch((cs_files, analysis_config))

    logging.debug(
        f"Using parallel {analysis_type} analysis for {len(cs_files)} files with {max_workers} workers"
    )

    try:
        # Split files into chunks
        file_chunks = chunk_list(cs_files, cs_analysis_chunk_size)
        all_results = {}
        completed_chunks = 0

        # Adaptive worker scaling based on file count
        if len(cs_files) < 200:
            scaled_workers = min(max_workers, 4)
        elif len(cs_files) < 1000:
            scaled_workers = min(max_workers, 8)
        else:
            scaled_workers = max_workers

        logging.debug(f"Processing {len(file_chunks)} chunks with {scaled_workers} workers")

        with ProcessPoolExecutor(max_workers=scaled_workers) as executor:
            # Submit all chunks
            future_to_chunk = {
                executor.submit(analyze_cs_files_batch, (chunk, analysis_config)): chunk
                for chunk in file_chunks
            }

            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                try:
                    chunk_results = future.result(timeout=300)
                    all_results.update(chunk_results)
                    completed_chunks += 1

                    # Progress reporting
                    if completed_chunks % 5 == 0 or completed_chunks == len(file_chunks):
                        logging.debug(
                            f"{analysis_type} analysis progress: {completed_chunks}/{len(file_chunks)} chunks completed"
                        )

                except Exception as e:
                    logging.warning(f"Error processing {analysis_type} analysis chunk: {e}")
                    completed_chunks += 1

        logging.debug(
            f"Parallel {analysis_type} analysis completed: {len(all_results)} files analyzed"
        )
        return all_results

    except Exception as e:
        logging.warning(
            f"Parallel {analysis_type} analysis failed: {e}. Falling back to sequential."
        )
        return analyze_cs_files_batch((cs_files, analysis_config))


def estimate_file_count(search_path: Path, pattern: str, sample_dirs: int = 5) -> int:
    """
    Estimate total file count by sampling a few directories.

    Args:
        search_path: Root directory to search
        pattern: File pattern to match
        sample_dirs: Number of directories to sample for estimation

    Returns:
        Estimated total file count
    """
    try:
        # Get first few directories for sampling
        dirs_to_sample = []
        dirs_to_sample.append(search_path)

        # Add a few subdirectories for sampling
        for subdir in search_path.rglob("*"):
            if subdir.is_dir() and len(dirs_to_sample) < sample_dirs:
                dirs_to_sample.append(subdir)
            if len(dirs_to_sample) >= sample_dirs:
                break

        # Count files in sample directories
        total_files_sampled = 0
        total_dirs_sampled = len(dirs_to_sample)

        for sample_dir in dirs_to_sample:
            files_in_dir = len(list(sample_dir.glob(pattern)))
            total_files_sampled += files_in_dir

        if total_dirs_sampled == 0:
            return 0

        # Estimate total directories (rough approximation)
        # This is much faster than enumerating all directories
        if total_dirs_sampled >= sample_dirs:
            # Estimate based on depth and breadth observed
            avg_files_per_dir = total_files_sampled / total_dirs_sampled
            estimated_total_dirs = max(total_dirs_sampled * 2, 10)  # Conservative estimate
            estimated_files = int(avg_files_per_dir * estimated_total_dirs)
        else:
            # Small directory structure, likely accurate count
            estimated_files = total_files_sampled

        logging.debug(
            f"File estimation: {total_files_sampled} files in {total_dirs_sampled} sampled dirs, "
            f"estimated total: {estimated_files}"
        )

        return estimated_files

    except Exception as e:
        logging.debug(f"File estimation failed: {e}, defaulting to 0")
        return 0


def find_files_with_pattern_parallel(
    search_path: Path,
    pattern: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    parallel_threshold: int = 50,
) -> List[Path]:
    """
    Optimized parallel file discovery with intelligent threshold detection.

    Key improvements:
    1. Uses file count estimation instead of directory enumeration
    2. Adaptive worker scaling based on estimated work
    3. Avoids unnecessary overhead for small file counts
    4. Falls back gracefully to sequential for small tasks

    Args:
        search_path: Directory to search
        pattern: File pattern to match
        max_workers: Maximum number of workers (auto-scaled)
        chunk_size: Directories per worker chunk
        disable_multiprocessing: Force sequential processing
        parallel_threshold: Minimum estimated files to use parallel processing

    Returns:
        List of matching file paths
    """
    # Force sequential if disabled
    if disable_multiprocessing or not MULTIPROCESSING_ENABLED:
        logging.debug(f"Using sequential file discovery for pattern '{pattern}' (disabled)")
        return list(search_path.rglob(pattern))

    # Estimate file count efficiently
    estimated_files = estimate_file_count(search_path, pattern)

    # Use sequential for small file counts (avoid overhead)
    if estimated_files < parallel_threshold:
        logging.debug(
            f"Using sequential file discovery for pattern '{pattern}' - "
            f"estimated {estimated_files} files < {parallel_threshold} threshold"
        )
        return list(search_path.rglob(pattern))

    # For larger file counts, use intelligent parallel processing
    logging.debug(
        f"Using parallel file discovery for pattern '{pattern}' - "
        f"estimated {estimated_files} files >= {parallel_threshold} threshold"
    )

    try:
        # NOW enumerate directories (only when we know we'll use parallel)
        all_dirs = [search_path] + [d for d in search_path.rglob("*") if d.is_dir()]

        # Adaptive worker scaling based on work size
        if estimated_files < 200:
            # Small-medium: Use fewer workers to reduce overhead
            scaled_workers = min(max_workers, 4)
        elif estimated_files < 1000:
            # Medium: Use moderate worker count
            scaled_workers = min(max_workers, 8)
        else:
            # Large: Use full worker count
            scaled_workers = max_workers

        logging.debug(
            f"Parallel processing: {len(all_dirs)} directories, "
            f"{scaled_workers} workers, {estimated_files} estimated files"
        )

        # Chunk the directories
        dir_chunks = chunk_list(all_dirs, chunk_size)
        all_results = []
        completed_chunks = 0

        with ProcessPoolExecutor(max_workers=scaled_workers) as executor:
            # Submit all chunks
            future_to_chunk = {
                executor.submit(find_files_with_pattern_chunk, (search_path, pattern, chunk)): chunk
                for chunk in dir_chunks
            }

            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                try:
                    chunk_results = future.result(timeout=300)
                    all_results.extend(chunk_results)
                    completed_chunks += 1

                    # Progress reporting every 10 chunks or at completion
                    if completed_chunks % 10 == 0 or completed_chunks == len(dir_chunks):
                        logging.debug(
                            f"File discovery progress: {completed_chunks}/{len(dir_chunks)} chunks completed"
                        )

                except Exception as e:
                    logging.warning(f"Error processing directory chunk: {e}")
                    completed_chunks += 1

        # Remove duplicates while preserving order
        seen = set()
        unique_results = []
        for path in all_results:
            if path not in seen:
                seen.add(path)
                unique_results.append(path)

        logging.debug(
            f"Parallel file discovery completed: found {len(unique_results)} unique files matching '{pattern}'"
        )
        return unique_results

    except Exception as e:
        logging.warning(f"Parallel file discovery failed: {e}. Falling back to sequential.")
        return list(search_path.rglob(pattern))


def extract_exclude_dirs(exclude_patterns: List[str]) -> Set[str]:
    """Extract directory names from exclude patterns for os.walk pruning.

    Converts patterns like '*/bin/*' to directory name 'bin'.
    Handles: '*/name/*', '**/name/**', '*/name'.
    Patterns with path separators in the name portion are ignored
    (they describe path-specific exclusions, not directory names).
    """
    dirs: Set[str] = set()
    for pat in exclude_patterns:
        parts = pat.replace("*", "").strip("/").strip("\\")
        if parts and "/" not in parts and "\\" not in parts:
            dirs.add(parts)
    return dirs


def walk_and_collect(
    search_path: Path,
    extensions: Set[str],
    exclude_dirs: Optional[Set[str]] = None,
) -> Dict[str, List[Path]]:
    """Single-pass directory walk collecting files by extension.

    Prunes excluded directories and dot-prefixed directories during traversal
    — they are never entered, avoiding the cost of enumerating their contents.
    This is critical for Docker volume mounts where every syscall crosses a
    protocol bridge (e.g., WSL2 9P on Windows).

    Does not follow symlinks (consistent with Path.rglob default behavior).
    Logs and continues on permission errors rather than aborting the walk.
    """
    if exclude_dirs is None:
        exclude_dirs = set()

    collected: Dict[str, List[Path]] = {ext: [] for ext in extensions}
    dirs_traversed = 0
    dirs_pruned = 0
    root = str(search_path)
    ext_tuple = tuple(extensions)  # for str.endswith short-circuit

    def _walk_error(err):
        logging.debug(f"Skipping directory during walk: {err}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=_walk_error):
        dirs_traversed += 1

        # Prune excluded and dot-prefixed directories in-place
        # (os.walk won't descend into removed entries)
        original_count = len(dirnames)
        dirnames[:] = [
            d for d in dirnames
            if d not in exclude_dirs and not d.startswith(".")
        ]
        dirs_pruned += original_count - len(dirnames)

        for filename in filenames:
            # Short-circuit: endswith(tuple) avoids splitext for non-matching files
            if filename.endswith(ext_tuple):
                ext = os.path.splitext(filename)[1]
                collected[ext].append(Path(os.path.join(dirpath, filename)))

    logging.info(
        f"File discovery: walked {dirs_traversed} directories, "
        f"pruned {dirs_pruned}, collected "
        + ", ".join(f"{len(v)} {k}" for k, v in collected.items())
    )
    return collected
