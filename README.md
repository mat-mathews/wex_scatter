# scatter.py
*a mini source code analysis tool*

"If I change this class in `MyCoreLibrary`, which other projects are actually using it?" Or, "What's the potential blast radius if I merge this feature branch?" Scatter is a proof-of-concept utility designed to help answer these questions by digging through a codebase to find potential "consumers" of code changes.

It's not a full-blown static analysis engine, but it provides a quick way to identify dependent projects, which can help in assessing risk, planning testing, or identifying CI/CD pipelines that need to be triggered. If pipeline data is provided, it will attempt to map these consuming projects to their respective pipelines in the output. **It can also optionally use the Google Gemini API to summarize the relevant C# files found in those projects.**

It works in three main ways:

* **Git Branch Analysis**: You provide a feature branch and a base branch (e.g., `main`). It analyzes the `.cs` files changed on your feature branch, identifies the types (`class`, `struct`, `interface`, `enum`) declared within them, and then searches the rest of your codebase for projects that might be using those specific types.
* **Target Project Analysis**: You point it directly at a `.csproj` file. It then searches for other projects that reference this target and potentially use its namespace, classes, or methods.
* **Stored Procedure Analysis**: You specify a stored procedure name. It finds C# files that reference that procedure and then analyzes the consumers of the projects containing those references.

The goal is to provide a heads-up about downstream dependencies before you merge or deploy, helping you identify potential integration issues. The optional AI summarization offers a quick glance into the *purpose* of the consuming code.

---
## 🚀 Quick Start Examples

### Git Branch Analysis
Analyze changes on a feature branch against `main` in the current directory.
```powershell
python scatter.py --branch-name feature/new-widget --repo-path .
```

### Target Project Analysis
Find all consumers of a specific project and map them to CI/CD pipelines using a CSV file.
```powershell
python scatter.py --target-project .\MyDotNetApp\MyDotNetApp.csproj --search-scope . --pipeline-csv pipeline_mapping.csv
```

### Stored Procedure Analysis
Find projects and classes that ultimately consume a specific stored procedure.
```powershell
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

### Advanced Analysis with AI Summarization & JSON Output
Analyze a target project, generate AI-powered code summaries for consumers, and output all results to a structured JSON file.
```powershell
python scatter.py --target-project .\MyDotNetApp\MyDotNetApp.csproj --search-scope . --summarize-consumers --google-api-key YOUR_API_KEY --output-format json --output-file analysis_results.json
```

---
## 📋 Table of Contents

1.  [Quick Start Examples](#-quick-start-examples)
2.  [Installation](#installation)
3.  [How It Works](#how-it-works)
4.  [Configuration & Mapping](#configuration--mapping)
5.  [Command-Line Arguments](#command-line-arguments)
6.  [Understanding the Output](#understanding-the-output)
7.  [Technical Details](#technical-details)
8.  [Roadmap](#roadmap)

---
## Installation

These instructions will guide you through setting up the necessary environment to run the script.

### Prerequisites

1.  **Git**: For version control operations.
2.  **Python 3.8+**: Ensure it's added to your system's PATH.

### Steps

1.  **Install Python**:
    * **Check if installed:** Open a terminal and run `python --version`. If you see a Python 3.x version, you can skip this step.
    * **Install if needed:** Download the official installer from [python.org](https://www.python.org/downloads/). **Crucially**, during installation, make sure to check the box that says **"Add Python to PATH"**.

2.  **Clone the Repository**:
    * Open your terminal and navigate to the directory where you want to store the project.
    * Clone the repository:
        ```powershell
        git clone <repository_url>
        cd <repository_directory_name>
        ```

3.  **Create and Activate a Virtual Environment**:
    * Using a virtual environment is highly recommended to isolate dependencies. Inside the project directory, run:
        ```powershell
        # Create the virtual environment
        python -m venv .venv
        ```
    * Activate it:
        ```powershell
        # On Windows
        .\.venv\Scripts\Activate.ps1
        
        # On macOS/Linux
        source .venv/bin/activate
        ```
        Your terminal prompt should now indicate that the environment is active.

4.  **Install Dependencies**:
    * With the virtual environment active, install the required packages:
        ```powershell
        pip install -r requirements.txt
        ```

---
## How It Works

### Git Branch Mode
1.  **Find Merge Base**: It uses `git` to find the common ancestor commit between your feature branch and the base branch. This serves as the starting point for comparison.
2.  **Identify Changed Files**: It calculates the diff to find all `.cs` files that were added or modified.
3.  **Map Files to Projects**: For each changed file, it walks up the directory tree to find the nearest `.csproj`, associating the code with its parent project.
4.  **Extract Declared Types**: It reads the content of the changed files and uses a regular expression to find declarations of `class`, `struct`, `interface`, or `enum`.
5.  **Find Consumers**: For each project with changed types, it triggers the core consumer analysis logic to find other projects that use those types.

### Target Project & Stored Procedure Modes
1.  **Identify Target(s)**:
    * **Target Project**: You provide a `.csproj` file. The script parses it to determine its namespace (from `<RootNamespace>` or `<AssemblyName>`).
    * **Stored Procedure**: You provide a sproc name. The script scans the entire search scope for C# files referencing it and identifies their parent projects. These projects become the "targets" for analysis.
2.  **Find Consumers**: It then runs the core consumer analysis logic for each target.

### Core Consumer Analysis
This is the heart of the script, used by all modes to find consumers of a "target" project:
1.  **Scan Scope**: It finds all `.csproj` files within the `--search-scope` (excluding the target itself).
2.  **Filter by ProjectReference**: It parses each potential consumer's `.csproj` file, looking for a `<ProjectReference>` that points directly to the target. Only projects with a direct reference are kept.
3.  **Filter by Namespace Usage**: It scans the `.cs` files within each directly referencing project, looking for `using <TargetNamespace>;`. Only projects that both reference the target *and* use its namespace proceed.
4.  **Filter by Class/Method Name (Optional)**: If `--class-name` or `--method-name` is used, it performs a simple text search within the remaining consumer projects to further narrow down the results. **Important**: This is a basic text search and may include matches in comments or strings, which can lead to false positives.

### AI Summarization (Optional)
If `--summarize-consumers` is enabled:
1.  **Identify Relevant Files**: The script knows which `.cs` files in a consumer were responsible for the match (e.g., the file containing the specific class name).
2.  **Call Gemini API**: It sends the content of each relevant file to the configured Google Gemini model.
3.  **Generate & Store Summary**: The API returns a concise, 2-3 sentence summary of the file's primary purpose, which is then included in the final report.

---
## Configuration & Mapping

### Google API Key
To use the `--summarize-consumers` feature, you need a Google Gemini API Key.
1.  **Get an API Key** from the Google AI Studio.
2.  **Set the Key**:
    * **Environment Variable (Recommended)**: Set an environment variable named `GOOGLE_API_KEY`.
        ```powershell
        # In PowerShell (current session)
        $env:GOOGLE_API_KEY="YOUR_API_KEY_HERE"
        ```
    * **Command-Line Argument**: Use the `--google-api-key` flag when running the script.

### Pipeline Mapping
You can provide a CSV file (`--pipeline-csv`) to map project names to CI/CD pipeline names. This helps identify which build pipelines might need to be triggered. The CSV requires headers named `Application Name` and `Pipeline Name`.

### Batch Job Verification
If your project follows a convention where batch jobs are defined as subdirectories in a configuration repository, you can use the `--app-config-path` argument. Point it to your configuration repo, and the script will check if a consuming project corresponds to a known batch job, adding a "Verified" or "Unverified" status to the output.

---
## Command-Line Arguments

*(Ensure your terminal's current directory is within the Git repository you want to analyze if using Git Branch mode.)*

### Mode Selection (Choose ONE)

* `--branch-name <BRANCH>`: **Git Mode**. Analyzes changes on a specific branch.
* `--target-project <PATH>`: **Project Mode**. Analyzes consumers of a specific `.csproj` file or its directory.
* `--stored-procedure <SPROC_NAME>`: **Sproc Mode**. Analyzes consumers of projects that reference a stored procedure.

### Key Options

* `--search-scope <PATH>`: **(Required)** The root directory to search for consumer projects.
* `--output-format [console|csv|json]`: Sets the output format. **Default**: `console`.
* `--output-file <PATH>`: Writes results to a file. **Required** for `csv` and `json` formats.
* `--pipeline-csv <PATH>`: Path to a CSV file for mapping project names to pipeline names.
* `--app-config-path <PATH>`: Path to the app-config repository for batch job verification.
* `-v, --verbose`: Enables detailed DEBUG level logging for troubleshooting.

### Filtering Options

* `--class-name <CLASS>`: Narrows the search to consumers that use a specific class.
* `--method-name <METHOD>`: Further narrows the search to consumers that call a specific method. Requires `--class-name`.

### AI Summarization Options

* `--summarize-consumers`: Enables summarization of relevant C# files using the Gemini API.
* `--google-api-key <KEY>`: Your Google API Key (overrides the environment variable).
* `--gemini-model <MODEL>`: The Gemini model to use. **Default**: `gemini-1.5-flash`.

For a full list of arguments and defaults, run `python scatter.py --help`.

---
## Understanding the Output

* **Console**: Prints a human-readable report listing each target and its consumers. If summarization is enabled, it includes the AI-generated summaries.
* **CSV**: Generates a flat file with columns for `TargetProjectName`, `ConsumerProjectName`, `PipelineName`, `BatchJobVerification`, etc. The `ConsumerFileSummaries` column contains a JSON string of file paths mapped to their summaries.
* **JSON**: Produces a structured JSON file containing a `pipeline_summary` (a list of unique pipelines found) and `all_results` (a detailed list of each dependency relationship). This format is ideal for programmatic use.

---
## Technical Details

### Type Extraction Regex
In Git Branch mode, the script uses a regular expression to find type declarations in changed `.cs` files. It's designed to capture `class`, `struct`, `interface`, and `enum` declarations, including those with access modifiers, generics, and various keywords.

```python
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*" # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*" # Optional keywords
    r"(?:class|struct|interface|enum)\s+" # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)" # Capture type name (non-greedy)
    r"\s*(?::|{|where|<)", # Look for end of declaration
    re.MULTILINE
)
```

**Limitations**: This regex is not a full C# parser. It may be confused by complex generic constraints or code in comments that mimics a declaration. However, it is effective for most common coding patterns.

---
## Roadmap

This script is a proof-of-concept with potential for growth. Future enhancements could include:
-   **Enhanced AI Integration**: Use an LLM to summarize the *diff* itself in Git mode, providing more context on *what* changed.
-   **Performance Improvements**: Implement multiprocessing to parallelize analysis, especially consumer finding in large codebases.
-   **Configuration File**: Support a `config.ini` or `pyproject.toml` file to pre-set common search scopes, repo paths, and other options.
-   **Improved Accuracy**: Integrate with more robust C# parsing tools to reduce false positives from the text-based search.
-   **Transitive Dependency Analysis**: Find not just direct consumers, but consumers-of-consumers, up to a specified depth.
-   **Flexible Git Commits**: Allow comparing arbitrary commit hashes or tags, not just branches.

---
## Example commands


##  Mode 1: Git Branch Analysis (`--branch-name`)

### Basic Usage
Analyzes changes on a feature branch against the default `main` branch, assuming the repo is in the current directory.
```shell
python scatter.py --branch-name feature/new-widget --repo-path .
```

Specifying a Different Base Branch
Compares the feature branch against develop instead of main.

```Shell
python scatter.py --branch-name feature/hotfix --base-branch develop --repo-path /path/to/repo
```

Filtering by Class Name
Only analyzes consumers of the WidgetFactory class, provided it was declared in the changed files on the branch.

```Shell
python scatter.py --branch-name feature/refactor-widget --repo-path . --class-name WidgetFactory
```

Filtering by Method Name
Further filters to find consumers of the Create method on the WidgetFactory class.

```Shell
python scatter.py --branch-name feature/refactor-widget --repo-path . --class-name WidgetFactory --method-name Create
```

### Advanced Git Analysis with All Options
This command:

- Analyzes the feature/new-api branch against main.
- Limits the consumer search to the src/services directory.
- Maps consumer projects to pipelines using a CSV file.
- Verifies batch jobs using an app-config repo.
- Outputs the results to a JSON file.
- Enables verbose logging.

```Shell
python scatter.py \
  --branch-name feature/new-api \
  --repo-path . \
  --base-branch main \
  --search-scope src/services \
  --pipeline-csv build/pipeline_map.csv \
  --app-config-path ../health-benefits-app-config \
  --output-format json \
  --output-file reports/analysis_results.json \
  --verbose
```

## Mode 2: Target Project Analysis (--target-project)

### Basic Usage
Finds all consumers of a specific project within the specified search scope.

```Shell
python scatter.py --target-project src/MyCoreLibrary/MyCoreLibrary.csproj --search-scope .
```

Overriding the Namespace
Explicitly sets the target project's namespace, bypassing automatic detection.


```Shell
python scatter.py \
  --target-project src/LegacyLib/LegacyLib.csproj \
  --search-scope . \
  --target-namespace Company.Product.OldStuff
```

Filtering by Class and Method
Finds consumers of MyCoreLibrary that specifically use the Sanitize method of the InputHelper class.

```Shell
python scatter.py \
  --target-project src/MyCoreLibrary/MyCoreLibrary.csproj \
  --search-scope . \
  --class-name InputHelper \
  --method-name Sanitize
```

### Advanced Target Analysis with AI Summarization
This command:

- Analyzes consumers of the MyDotNetApp project.
- Enables AI summarization of the relevant consumer files.
- Provides the Google API key directly.
- Specifies a different Gemini model for summarization.
- Outputs the results to a CSV file.

```Shell
python scatter.py \
  --target-project MyDotNetApp/MyDotNetApp.csproj \
  --search-scope . \
  --summarize-consumers \
  --google-api-key "AIzaSy..." \
  --gemini-model gemini-1.5-pro \
  --output-format csv \
  --output-file reports/summary_report.csv
```

## Mode 3: Stored Procedure Analysis (--stored-procedure)

### Basic Usage
Finds projects that reference a specific stored procedure and then analyzes their consumers.

```Shell
python scatter.py --stored-procedure "dbo.usp_GetUserDetails" --search-scope .
```

Using a Custom Regex Pattern
Finds references to a stored procedure using a custom regex format where the name follows a specific prefix.

```Shell
python scatter.py \
  --stored-procedure "UpdateUser" \
  --search-scope . \
  --sproc-regex-pattern "EXECUTE sp_prefix_{sproc_name_placeholder}"
```


Filtering by Containing Class
After finding projects that reference the sproc, this only analyzes consumers of the UserDataAccess class within those projects.

```Shell
python scatter.py \
  --stored-procedure "dbo.usp_GetUserDetails" \
  --search-scope . \
  --class-name UserDataAccess
```

### Advanced Stored Procedure Analysis
This command:

- Finds projects referencing the sproc.
- Only analyzes consumers of the UserDataAccess class and its Fetch method.
- Outputs the detailed results to a JSON file.
- Uses verbose logging.

```Shell
python scatter.py \
  --stored-procedure "dbo.usp_GetUserDetails" \
  --search-scope . \
  --class-name UserDataAccess \
  --method-name Fetch \
  --output-format json \
  --output-file reports/sproc_consumers.json \
  --verbose
```