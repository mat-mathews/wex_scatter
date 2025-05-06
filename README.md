# scatter.py
*a mini source code analysis tool*

Question: "If I change this class in `MyCoreLibrary`, which other projects are actually using it?" Or maybe, "What's the potential blast radius if I merge this feature branch?". This isn't a full-blown Roslyn type tool, but this POC tries to help figure out dependent projects, which could help find a mapped pipeline for CI/CD.

Scatter is a utility to dig through the codebase to find potential "consumers" of code changes. **It can optionally use the Google Gemini API to summarize the relevant C# files found in those consuming projects.** It works in two main ways:

* **Git Branch Analysis**: You give it a feature branch and a base branch (like `main`), and it analyzes the `.cs` files changed on your feature branch. It figures out which projects those files belong to, identifies the types (`class`, `struct`, `interface`, `enum`) declared within them, and then searches the rest of your codebase for projects that might be using those specific types.
* **Target Project Analysis**: You point it directly at a specific `.csproj` file (or the directory containing it). It then searches the rest of your codebase for projects that reference this target project and potentially use its namespace, classes, or methods (if you specify filters).

The goal is to give you a heads-up about downstream dependencies before you merge or deploy, helping you identify potential integration issues or areas that need extra testing. The optional summarization provides basic insights into the *content* of the consuming code.

## Table of Contents (TBD)

1.  [Installation](#installation-windows-using-powershell)
2.  [How It Works](#how-it-works)
3.  [Pipeline Mapping](#pipeline-mapping)
4.  [Usage & Examples](#usage--examples)
5.  [Understanding the Output](#understanding-the-output)
6.  [Understanding the Type Extraction Regex](#understanding-the-type-extraction-regex)
7.  [TODO & Roadmap](#todo--roadmap)

## Installation (Windows using PowerShell)

These instructions will guide you through setting up the necessary environment to run this script on a Windows machine using PowerShell.

### Prerequisites

1.  **Windows PowerShell** 
2.  **Git**
3.  **Python**

### Steps

1.  **Install Python:**
    * **Check if installed:** Open PowerShell and run `py --version` or `python --version`. If you see a Python 3.x version (e.g., `Python 3.10.7`), you can skip this step.
    * **Install if needed:**
        * **(Recommended Method):** Install Python from the Microsoft Store. Search for "Python 3.1x" (e.g., Python 3.11 or 3.12) and install it. This method usually handles PATH setup automatically.
        * **(Alternative Method):** Download the official Windows installer from [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/). **Crucially**, during installation, make sure to check the box that says **"Add Python 3.x to PATH"**.
    * **Verify:** Close and reopen PowerShell. Run `py --version` or `python --version` again to confirm the installation.

2.  **Clone the Repository:**
    * Open PowerShell and navigate to the directory where you want to store the project (use `cd path\to\your\directory`).
    * Clone the repository using Git (replace `<repository_url>` with the actual URL):
        ```powershell
        git clone <repository_url>
        ```
    * Navigate into the newly cloned directory (replace `<repository_directory_name>` with the actual folder name created by `git clone`):
        ```powershell
        cd <repository_directory_name>
        ```

3.  **Create and Activate a Virtual Environment:**
    * Using a virtual environment is highly recommended to isolate project dependencies. Inside the project directory, run the following command to create a virtual environment named `.venv`:
        ```powershell
        # Ensure you are using Python 3. Use 'py' if 'python' points to Python 2 or isn't found.
        py -m venv .venv
        # Or, if 'python' correctly points to Python 3:
        # python -m venv .venv
        ```
    * Activate the virtual environment. This changes your shell prompt to indicate the environment is active:
        ```powershell
        .\.venv\Scripts\Activate.ps1
        ```
    * **Troubleshooting Activation:** If you get an error about script execution being disabled, you might need to adjust PowerShell's execution policy for the current user or process. You can temporarily allow scripts for the current session by running:
        ```powershell
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
        ```
        Then try activating the environment again. *Note: Be cautious about changing execution policies.*

4.  **Install Dependencies:**
    * Create a file named `requirements.txt` in the root of the project directory with the following content:
        ```txt
        google-generativeai
        GitPython
        ```
    * Ensure your virtual environment is still active (you should see `(.venv)` at the start of your PowerShell prompt). Install the required packages using `pip`:
        ```powershell
        pip install -r requirements.txt
        ```
        This command reads the `requirements.txt` file and installs the specified libraries into your virtual environment.

5.  **(Optional) Verify Installation:**
    * Run the script with the `--help` flag to ensure it starts correctly and can parse arguments (replace `your_script_name.py` with the actual name of your Python script file):
        ```powershell
        python your_script_name.py --help
        ```
    * You should see the script's help message outlining the available command-line arguments.

### Configuration (Google API Key)

This script uses the Google Gemini API for summarizing code (`--summarize-consumers` option). To use this, you need a Google API Key.

1.  **Get an API Key**
2.  **Use the Key:**
    * **Environment Variable (Recommended):** Set an environment variable named `GOOGLE_API_KEY`. In PowerShell (for the current session):
        ```powershell
        $env:GOOGLE_API_KEY = "YOUR_API_KEY_HERE"
        ```
        To set it permanently, search for "Edit the system environment variables" in Windows search.
    * **Command-Line Argument:** Use the `--google-api-key` argument when running the script:
        ```powershell
        python your_script_name.py --google-api-key YOUR_API_KEY_HERE [other arguments...]
        ```

Remember to activate the virtual environment (`.\.venv\Scripts\Activate.ps1`) in your session each time you want to run the script.

## How It Works

Let's break down the process depending on the mode.

### Git Branch Mode Steps

1.  **Find Merge Base**: It uses `git merge-base` to find the best common ancestor commit between your feature branch and the base branch. This commit acts as the starting point for comparison.
2.  **Identify Changed Files**: It calculates the diff between the merge base and the tip of your feature branch to find all changed files.
3.  **Filter for C# Files**: It specifically looks for files ending in `.cs` that were Added, Modified, Renamed, or Copied.
4.  **Map Files to Projects**: For each changed `.cs` file, it walks up the directory tree within the Git commit's structure to find the nearest `.csproj` file. This associates the changed code with its parent project.
5.  **Extract Declared Types**: It reads the content of the changed `.cs` files (from your local working copy) and uses a regular expression (see below) to find declarations of `class`, `struct`, `interface`, or `enum`.
6.  **Find Consumers**: For each project that had changed types, it triggers the consumer analysis logic (described next) to find other projects in your specified scope that might be using those types.

### Target Project Mode Steps

1.  **Identify Target**: You provide the path to a specific `.csproj` file or its containing directory.
2.  **Determine Namespace**: It tries to parse the `.csproj` file to find the `<RootNamespace>` or `<AssemblyName>`. If it can't find either, it falls back to using the project file's name (e.g., `MyLibrary.csproj` -> `MyLibrary`) as the namespace. You can also override this with the `--target-namespace` argument.
3.  **Find Consumers**: It triggers the consumer analysis logic (described next) using the target project and its determined namespace, applying any `--class-name` or `--method-name` filters you provided.

### Finding Consumers (The Core Stuff)

This is the heart of the analysis, used by both modes. When looking for consumers of a specific "target" project:

1.  **Scan Scope**: It finds all `.csproj` files within the `--search-scope` directory (excluding the target project itself). These are potential consumers.
2.  **Filter by ProjectReference**: It parses each potential consumer's `.csproj` file, looking for `<ProjectReference>` elements that point directly to the target project file. Only projects with a direct reference move to the next step. (It tries to be smart and skip references that look like MSBuild properties, e.g., `$(SolutionDir)\...`).
3.  **Filter by Namespace Usage**: If a reliable namespace was determined for the target project, it scans the `.cs` files within each directly referencing consumer project. It looks for `using <TargetNamespace>;` or `global using <TargetNamespace>;` statements. Only projects that both reference the target *and* use its namespace proceed (unless the namespace couldn't be found, in which case all direct referencers pass this step). The specific `.cs` file(s) where the namespace was found are tracked.
4.  **Filter by Class Name (Optional)**: If you provided `--class-name` (or if running in Git mode and a specific changed type is being checked), it performs a simple text search *within the previously tracked relevant .cs files* of the remaining consumer projects. It looks for the class name as a whole word (`\bClassName\b`). Only consumers where the class name is found in those files proceed. The tracked relevant files are updated to *only* those containing the class name. **Important**: This is a basic text search and might find matches in comments, variable names, or strings, potentially leading to false positives.
5.  **Filter by Method Name (Optional)**: If you provided both `--class-name` and `--method-name`, it performs another simple text search *within the currently tracked relevant .cs files* (those that passed the class filter). It looks for patterns like `.MethodName(`. Only consumers where the method pattern is found proceed. The tracked relevant files are updated again. **Again**, this is very basic and doesn't understand context – more potential for false positives.

The projects that make it through all applicable filters are reported as the final consumers. The list of relevant `.cs` files associated with each consumer reflects the files that passed the *deepest* applied filter.

### Summarizing Consumers (Optional)

If the `--summarize-consumers` flag is used:

1.  **Identify Relevant Files:** After the filtering steps above, the script knows which specific `.cs` file(s) in each consuming project were responsible for it matching the criteria (e.g., the file containing the specific class name or method call).
2.  **Call Gemini API:** For each of these relevant files, the script reads its content and sends it to the configured Google Gemini model (e.g., `gemini-1.5-flash`).
3.  **Generate Summary:** The prompt asks the API for a concise summary (2-3 sentences) of the file's primary purpose.
4.  **Store Result:** The summary text (or an error message if generation fails) is stored alongside the consumer information.

*Note: Using this involves making API calls to Google Cloud.*

## Pipeline Mapping

You can optionally provide a CSV file (`--pipeline-csv`) mapping project names (like `MyConsumerApp`) to pipeline names (like `my-consumer-app-ci`). If provided, the script will look up the consumer project's name (derived from its filename) in the CSV and add the corresponding pipeline name to the output. This is handy if you want to know which build pipelines might need to be triggered based on the analysis results. The CSV needs columns named `Project Name` and `Pipeline Name`.

*We need a good CSV mapping of projects compiled, likely with the help of domain teams or SMEs*

## Usage & Examples

You run the script from your command line using `python your_script_name.py ...`. Here's a breakdown of the arguments:

*(Make sure your current directory is somewhere within the Git repository you want to analyze if using Git Branch mode without specifying an absolute `--repo-path`.)*

### Mode Selection (Required)

You **MUST** choose one of these two modes:

* `--target-project /path/to/project/dir`
    * **What:** Tells the script to analyze consumers of a specific project. You can provide the direct path to the `.csproj` file or the path to the directory containing it (it will find the first `.csproj` in that directory).
    * **Example:**
        ```powershell
        python your_script_name.py --target-project src/MyCoreLibrary --search-scope .
        ```
        *(Analyzes consumers of the project found in `src/MyCoreLibrary`, searching the entire current directory `.`)*

**OR**

* `--branch-name <your-feature-branch>`
    * **What:** Tells the script to analyze changes on a specific Git feature branch compared to a base branch.
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name feature/new-widget --base-branch main --repo-path .
        ```
        *(Analyzes changes on `feature/new-thingamajig` compared to `main`, assuming the repo is in the current directory `.`)*

### Git Branch Mode Options

These are relevant only when using `--branch-name`:

* `-r PATH, --repo-path PATH`
    * **What:** Specifies the path to the root of your Git repository.
    * **Default:** `.` (the current directory)
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature -b develop --repo-path /path/to/my/solution/root
        ```

* `-b BRANCH, --base-branch BRANCH`
    * **What:** The base branch to compare your feature branch against (e.g., `main`, `develop`, `master`).
    * **Default:** `main`
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature --base-branch develop
        ```
        *(Compares `my-feature` against `develop`)*

### Common Options (Both Modes)

These can be used with either `--target-project` or `--branch-name`:

* `--search-scope PATH`
    * **What:** The root directory where the script should look for potential consumer projects.
    * **Required?:** Yes, unless you are using `--branch-name` and omit this argument, in which case it defaults to the `--repo-path`. It's required when using `--target-project`.
    * **Example (Target Mode):**
        ```powershell
        python your_script_name.py --target-project src/Core --search-scope src
        ```
        *(Looks for consumers of `src/Core` only within the `src` directory)*
    * **Example (Git Mode):**
        *Defaults to repo-path (current dir `.`), searching everything*
        ```powershell
        python your_script_name.py --branch-name my-feature
        ```
        *Explicitly limit search scope*
        ```powershell
        python your_script_name.py --branch-name my-feature --search-scope src/Applications
        ```

* `--class-name CLASSNAME`
    * **What:** Filters the consumer analysis.
        * In Git Branch mode, it only analyzes consumers for this specific class, but only if that class name was actually found among the types declared in the changed files on the branch.
        * In Target Project mode, it finds consumers that reference the target project and also contain text matching this class name.
    * **Default:** None (no class filtering)
    * **Example (Target Mode):**
        ```powershell
        python your_script_name.py --target-project src/Utils --search-scope . --class-name StringHelper
        ```
    * **Example (Git Mode):**
        ```powershell
        python your_script_name.py --branch-name feature/cleanup --class-name ObsoleteDataMapper
        ```
        *(Will only report consumers if `ObsoleteDataMapper` was declared in changed files and other projects use it)*

* `--method-name METHODNAME`
    * **What:** Further filters the consumer analysis to look for basic text patterns like `.MethodName(`.
    * **Requires:** `--class-name` must also be provided. This filter is only applied to consumers that already passed the class name filter.
    * **Default:** None
    * **Example:**
        ```powershell
        python your_script_name.py --target-project src/Utils --search-scope . --class-name StringHelper --method-name SanitizeInput
        ```

* `--target-namespace NAMESPACE`
    * **What:** Explicitly tells the script the namespace of the target project. This overrides the automatic detection from the `.csproj`. Mainly useful in Target Project mode if automatic detection fails or is incorrect.
    * **Default:** None (automatic detection)
    * **Example:**
        ```powershell
        python your_script_name.py --target-project src/LegacyLib --search-scope . --target-namespace Company.Product.LegacyStuff
        ```

* `--pipeline-csv /path/to/mapping.csv`
    * **What:** Path to a CSV file mapping `Project Name` to `Pipeline Name`.
    * **Default:** None
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature --pipeline-csv cicd/pipeline-map.csv
        ```

* `--output-file /path/to/results.csv`
    * **What:** Writes the analysis results to a CSV file instead of printing to the console.
    * **Default:** None (prints to console)
    * **Example:**
        ```powershell
        python your_script_name.py --target-project src/Core --search-scope . --output-file analysis_results.csv
        ```

* `-v, --verbose`
    * **What:** Enables detailed DEBUG level.
    * **Default:** False (uses INFO level logging)
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature -v
        ```

* `--summarize-consumers`
    * **What:** Enables summarization of relevant C# files in consuming projects using the Google Gemini API. Requires API key configuration.
    * **Default:** False
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature --summarize-consumers --google-api-key YOUR_API_KEY
        ```

* `--google-api-key YOUR_API_KEY`
    * **What:** Provide the Google API Key directly via command line (overrides environment variable).
    * **Default:** None (uses `GOOGLE_API_KEY` environment variable)
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature --summarize-consumers --google-api-key "AIza..."
        ```

* `--gemini-model MODEL_NAME`
    * **What:** Specify the Gemini model to use for summarization.
    * **Default:** `gemini-1.5-flash`
    * **Example:**
        ```powershell
        python your_script_name.py --branch-name my-feature --summarize-consumers --gemini-model gemini-pro
        ```

## Understanding the Output

* **Console Output:** When printing to the console, the script lists each target project and the type/level that triggered the analysis. Underneath, it lists the consuming projects found. If `--summarize-consumers` is enabled, it will print the relative path and the Gemini-generated summary for each relevant file within that consumer, indented below the consumer project line.
* **CSV Output (`--output-file`)**: The CSV file contains columns for `TargetProjectName`, `TargetProjectPath`, `TriggeringType`, `ConsumerProjectName`, `ConsumerProjectPath`, `PipelineName`, and `ConsumerFileSummaries`. The `ConsumerFileSummaries` column will contain a JSON-formatted string mapping the relative paths of summarized files to their summary text (e.g., `"{\"path/to/file1.cs\": \"Summary 1...\", \"path/to/file2.cs\": \"Summary 2...\"}"`).

## Understanding the Type Extraction Regex

In Git Branch mode, the script needs to find type declarations in the changed `.cs` files. It uses this Python `re.compile` pattern:

```python
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*" # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*" # Optional keywords
    r"(?:class|struct|interface|enum)\s+" # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)" # Capture type name (non-greedy) - handles generics roughly
    r"\s*(?::|{|where|<)", # Look for inheritance colon, opening brace, where clause, or start of generics
    re.MULTILINE
)
```

Here's a rough breakdown:

- `^\s*`: Matches the beginning of a line (due to re.MULTILINE) followed by any whitespace.
- `(?:public|internal|private|protected)?\s*`: Optionally matches an access modifier keyword, followed by whitespace. (?:...) is a non-capturing group. ? makes it optional.
- `(?:static\s+|abstract\s+|sealed\s+|partial\s+)*`: Optionally matches common keywords like static, abstract, sealed, or partial (zero or more times, *), followed by whitespace.
- `(?:class|struct|interface|enum)\s+`: Matches the core type keyword (class, struct, etc.) followed by one or more whitespace characters.
- `([A-Za-z_][A-Za-z0-9_<>,\s]*?)`: This is the capturing group ((...)) for the type name itself. [A-Za-z_]: Starts with a letter or underscore. [A-Za-z0-9_<>,\s]*?: Followed by zero or more letters, numbers, underscores, angle brackets (<> for generics), commas (within generics), or whitespace. The *? makes it non-greedy, trying to match the shortest possible string. This is a basic attempt to handle generic types like MyClass<T> or MyClass<T, U>.
- `\s*(?::|{|where|<)`: Matches optional whitespace followed by a character that typically ends a type declaration signature: an inheritance colon :, an opening brace {, a generic constraint where clause, or the start of a generic parameter list <. This helps the non-greedy match in step 5 stop correctly. 

Limitations: This regex is not a full C# parser obviously. It might get confused by complex generic constraints, nested types defined weirdly, or code inside comments/strings that happens to look like a declaration. However, it works reasonably well for common declaration patterns. The script then does some basic cleanup to remove the <...> part if captured.

## TODO & Roadmap

This script could be useful as it's flushed out and hardened, maybe a lot we could build here. Some ideas for the future:

- Real LLM Integration or an actual data pipeline - Diff Summaries: When running in Git Branch mode, use an LLM to summarize the specific changes made within the affected files on the branch, giving more context than just listing the changed files.
- Vector Embeddings: Explore creating a vector database for the content of discovered related C# files and potentially their project contexts. This could enable more advanced semantic searching like "find code that does something similar to this changed class".
- Refactor to use a factory pattern for input and discovery of projects for extensibility.
- Performance Boost: Implement multiprocessing or threading to parallelize the analysis (especially consumer finding across multiple projects) for significant speed improvements in large codebases. Also potentially optimize file reading/caching.
- Configuration File: Add support for loading settings from a config file (like .ini or pyproject.toml). This would let users define multiple search scopes, target directories, pipeline mappings, and potentially pre-set branch names for easier execution of common scenarios.
- Improved Accuracy: Refine the text-based searching for classes/methods or explore integrating with more robust C# parsing tools (like Roslyn via Python interop, though that adds complexity) to reduce false positives.
- Better Reporting: Offer more flexible output formats or visualizations.
- Transitive Dependency Analysis: Find not just direct consumers, but consumers-of-consumers, up to a specified depth.
- Exclude Directories: Allow specifying directories (like tests, bin, obj) to ignore during the consumer search, speeding up analysis and reducing noise.
- Flexible Git Commit Specification: Allow comparing arbitrary commits/tags instead of only branches based on merge-base.

