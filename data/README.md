# Evidence data

controlled/ contains supplied model inputs, scored rows and summaries.
logs/ groups trace material by empirical method; its README and inventory
identify the collections. observational/ holds separate source reports and
supplementary records. manifests/ documents release transformations.

The section, table, and figure mapping is in docs/paper_map.csv. Delivered
tables and figures are in results/. Offline analysis writes outputs/analysis
without overwriting these inputs. Missing and incomplete observations remain
explicit rather than being turned into failure or zero-cost observations.

Source IDs inside rows are preserved. Host-local paths and detected
credentials are redacted in release copies; source and released hashes differ
where documented. A release hash verifies these copies, not original provider
authenticity or complete historical-run provenance.
