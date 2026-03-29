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

Verify the image works:

```bash
docker run scatter --help
```

The examples below use scatter's own sample projects. Mount the repo at `/workspace` and run any command. The `-v scatter-cache:/workspace/.scatter` volume keeps the dependency graph cache across runs — without it, scatter rebuilds the graph from scratch every time (~40s for 800 projects).

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

### AI features

Pass your API key via environment variable:

```bash
docker run \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -v $(pwd):/workspace \
  -v scatter-cache:/workspace/.scatter \
  scatter --sow "Add tenant isolation to portal config" --search-scope /workspace
```

### Interactive session

Drop into a shell inside the container:

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

```bash
docker run \
  -v $(pwd):/workspace \
  -v /tmp/scatter-out:/output \
  scatter --target-project /workspace/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope /workspace \
    --output-format json --output-file /output/report.json
```

The report is written to `/tmp/scatter-out/report.json` on your host.
