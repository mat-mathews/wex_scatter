import argparse
import csv
from pathlib import Path
import yaml # Requires PyYAML: pip install PyYAML
import pandas as pd # Requires pandas: pip install pandas
from collections import Counter

def parse_pipeline_artifact(file_path: Path) -> tuple[dict | None, str]:
    """
    Parses a single Azure DevOps YAML pipeline file to extract the
    pipeline name and the primary application artifact name.

    Args:
        file_path: The Path object for the YAML file.

    Returns:
        A tuple containing:
        - A dictionary with the pipeline and artifact name (or None on failure).
        - A status string ('SUCCESS', 'NO_ARTIFACT', 'YAML_ERROR', 'UNEXPECTED_ERROR').
    """
    pipeline_name = file_path.stem
    print(f"Processing: {pipeline_name}...")

    try:
        # Read the raw file content first to handle invalid characters.
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # The YAML spec forbids tabs for indentation, so we replace them with
        # spaces before parsing to prevent errors.
        content_with_spaces = content.replace('\t', '  ')

        data = yaml.safe_load(content_with_spaces)

        # The artifact name is consistently found in this nested structure.
        # Using .get() provides a safe way to access nested keys that may not exist.
        artifact_name = (data.get('extends', {})
                             .get('parameters', {})
                             .get('CIPack', {})
                             .get('artifactName'))

        def create_result(artifact):
            parts = artifact.split('_', 1)
            app_name = parts[1] if len(parts) > 1 else parts[0]
            print(f"  -> SUCCESS: Found Artifact: {artifact} (App: {app_name})")
            return {
                "Pipeline Name": pipeline_name,
                "Application Artifact": artifact,
                "Name": app_name
            }, "SUCCESS"

        if artifact_name:
            return create_result(artifact_name)
        
        # Fallback: Check trigger tags if artifactName is not found in the primary location.
        print(f"  -> INFO: 'artifactName' not in CIPack. Checking resource trigger tags...")
        
        # Ensure resources and pipelines keys exist and are lists before accessing.
        pipelines_list = data.get('resources', {}).get('pipelines', [])
        if pipelines_list and isinstance(pipelines_list, list) and len(pipelines_list) > 0:
            tags = pipelines_list[0].get('trigger', {}).get('tags', [])
            if tags and isinstance(tags, list) and len(tags) > 0:
                tag_artifact = tags[0]
                return create_result(tag_artifact)

        print("  -> FAILED: Could not determine artifact name for this pipeline.")
        return None, "NO_ARTIFACT"

    except yaml.YAMLError as e:
        print(f"  -> ERROR: Could not parse YAML file {file_path.name}. Error: {e}")
        return None, "YAML_ERROR"
    except Exception as e:
        print(f"  -> ERROR: An unexpected error occurred while processing {file_path.name}. Error: {e}")
        return None, "UNEXPECTED_ERROR"

def main():
    """
    Main function to run the script.
    """
    parser = argparse.ArgumentParser(
        description="Parse Azure DevOps YAML pipelines to map pipeline names to application artifacts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "search_directory",
        help="The directory to search for YAML/YML pipeline files."
    )
    parser.add_argument(
        "-o", "--output-file",
        default="pipeline_to_app_mapping.csv",
        help="The name of the output CSV spreadsheet file."
    )
    args = parser.parse_args()

    search_path = Path(args.search_directory)
    output_path = Path(args.output_file)

    if not search_path.is_dir():
        print(f"Error: The specified search directory does not exist: {search_path}")
        return

    pipeline_files = list(search_path.glob('*.yml')) + list(search_path.glob('*.yaml'))

    if not pipeline_files:
        print(f"No YAML (.yml, .yaml) files found in '{search_path}'.")
        return

    total_files = len(pipeline_files)
    print(f"Found {total_files} pipeline files to process.\n")

    results = []
    # Use a Counter to track the status of each processed file.
    stats = Counter()

    for file in sorted(pipeline_files):
        result, status = parse_pipeline_artifact(file)
        stats[status] += 1
        if result:
            results.append(result)

    print("\n" + "="*50)
    print("Processing Summary")
    print("="*50)
    print(f"Total Files Found:      {total_files}")
    print(f"Successfully Parsed:    {stats['SUCCESS']}")
    print(f"Failed (No Artifact):   {stats['NO_ARTIFACT']}")
    print(f"Failed (YAML Error):    {stats['YAML_ERROR']}")
    print(f"Failed (Unexpected):    {stats['UNEXPECTED_ERROR']}")
    print("="*50 + "\n")


    if not results:
        print("Processing complete. No valid pipeline artifacts were found to export.")
        return

    print(f"Exporting {len(results)} successful mappings to {output_path}...")
    try:
        df = pd.DataFrame(results)
        if 'Name' in df.columns:
            df = df[["Pipeline Name", "Application Artifact", "Name"]]
            
        df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
        print("Spreadsheet created successfully.")
    except Exception as e:
        print(f"Error: Failed to write to spreadsheet file. {e}")

if __name__ == "__main__":
    main()