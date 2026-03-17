# Reports

## Console Reporter

::: scatter.reports.console_reporter
    options:
      members:
        - print_console_report
        - print_filter_pipeline
        - render_tree
        - print_impact_report

## JSON Reporter

::: scatter.reports.json_reporter
    options:
      members:
        - prepare_detailed_results
        - write_json_report
        - write_impact_json_report

## CSV Reporter

::: scatter.reports.csv_reporter
    options:
      members:
        - write_csv_report
        - write_impact_csv_report

## Markdown Reporter

::: scatter.reports.markdown_reporter
    options:
      members:
        - build_markdown
        - write_markdown_report
        - build_impact_markdown
        - write_impact_markdown_report
        - build_graph_markdown
        - write_graph_markdown_report

## Graph Reporter

::: scatter.reports.graph_reporter
    options:
      members:
        - generate_mermaid
        - write_graph_csv_report
        - print_graph_report
        - build_graph_json
        - write_graph_json_report
