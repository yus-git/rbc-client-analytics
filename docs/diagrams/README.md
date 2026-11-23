# Editable architecture diagrams

These SVGs include native draw.io XML. They render directly in GitHub and can be
opened in draw.io Desktop for editing; they are not flattened screenshots.

- [Data paths](data-paths.drawio.svg): actual Direct Lake, DirectQuery and Import routes.
- [Focused semantic views](semantic-stars.drawio.svg): shared dimensions shown
  repeatedly for readability, not duplicated model tables.
- [Private Databricks option](databricks-private.drawio.svg): VNet injection,
  workspace Private Link, gateway connections and separate ADLS access.

Keep embedded model XML when re-exporting. After a change, inspect the rendered
diagram as well as its XML; well-formed XML alone does not prove readable labels
or correct routing.
