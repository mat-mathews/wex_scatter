# Docker

Run scatter without installing Python or uv. Mount a .NET repo into the container and analyze it.

## Build the image

```bash
git clone https://github.com/mat-mathews/wex_scatter.git
cd wex_scatter
docker build -t scatter .
```

## Usage

In the commands below, `scatter` at the end of `docker run ... scatter` is the Docker image name — scatter's CLI arguments follow after it.

Make sure Docker Desktop is running (whale icon in menu bar / system tray), then verify the image works:

```bash
docker run scatter --help
```

The examples below use scatter's own sample projects. Mount the repo at `/workspace` and run any command. The `-v scatter-cache:/workspace/.scatter` volume keeps the dependency graph cache across runs — without it, scatter rebuilds the graph from scratch every time (~40s for 800 projects).

=== "Windows (PowerShell)"

    ```powershell
    # Find consumers of a project
    docker run `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace

    # Analyze a stored procedure
    docker run `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope /workspace

    # Dependency graph health
    docker run `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --graph --search-scope /workspace

    # Git branch blast radius (run from any branch with .cs changes)
    docker run `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --branch-name main --repo-path /workspace
    ```

=== "macOS / Linux"

    ```bash
    # Find consumers of a project
    docker run \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace

    # Analyze a stored procedure
    docker run \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope /workspace

    # Dependency graph health
    docker run \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --graph --search-scope /workspace

    # Git branch blast radius (run from any branch with .cs changes)
    docker run \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --branch-name main --repo-path /workspace
    ```

First run builds the graph and caches it. Subsequent runs with the cache volume patch incrementally (~10ms for typical edits).

### Hybrid AST mode

The Docker image includes tree-sitter, so `--parser-mode hybrid` works out of the box. Add it to any consumer analysis command to filter false positives from comments and string literals:

=== "Windows (PowerShell)"

    ```powershell
    docker run `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace `
        --class-name PortalDataService --parser-mode hybrid
    ```

=== "macOS / Linux"

    ```bash
    docker run \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace \
        --class-name PortalDataService --parser-mode hybrid
    ```

No API key needed — this uses tree-sitter (a local C parser), not an LLM.

### AI features

Pass your API key via environment variable:

=== "Windows (PowerShell)"

    ```powershell
    docker run `
      -e GOOGLE_API_KEY=$env:GOOGLE_API_KEY `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter --sow "Add tenant isolation to portal config" --search-scope /workspace
    ```

=== "macOS / Linux"

    ```bash
    docker run \
      -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter --sow "Add tenant isolation to portal config" --search-scope /workspace
    ```

### Interactive session

Drop into a shell inside the container:

=== "Windows (PowerShell)"

    ```powershell
    # With a local repo mounted
    docker run -it --entrypoint /bin/bash `
      -v "${PWD}:/workspace" `
      -v scatter-cache:/workspace/.scatter `
      scatter

    # Or clone inside the container
    docker run -it --entrypoint /bin/bash scatter
    # inside the container:
    git clone https://your-repo-url /workspace/repo
    scatter --target-project /workspace/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace/repo
    ```

=== "macOS / Linux"

    ```bash
    # With a local repo mounted
    docker run -it --entrypoint /bin/bash \
      -v $(pwd):/workspace \
      -v scatter-cache:/workspace/.scatter \
      scatter

    # Or clone inside the container
    docker run -it --entrypoint /bin/bash scatter
    # inside the container:
    git clone https://your-repo-url /workspace/repo
    scatter --target-project /workspace/repo/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace/repo
    ```

## Output files

To write JSON, CSV, or markdown reports to your host machine, mount an output directory:

=== "Windows (PowerShell)"

    ```powershell
    docker run `
      -v "${PWD}:/workspace" `
      -v C:/scatter-out:/output `
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace `
        --output-format json --output-file /output/report.json
    ```

    The report is written to `C:\scatter-out\report.json` on your host.

=== "macOS / Linux"

    ```bash
    docker run \
      -v $(pwd):/workspace \
      -v /tmp/scatter-out:/output \
      scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace \
        --output-format json --output-file /output/report.json
    ```

    The report is written to `/tmp/scatter-out/report.json` on your host.
