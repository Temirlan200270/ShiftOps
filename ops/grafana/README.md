# Grafana dashboards (as code)

Two dashboards drive the on-call experience for ShiftOps:

| File                            | Audience              | Goal                                                |
| ------------------------------- | --------------------- | --------------------------------------------------- |
| `shiftops-operations.json`      | engineers / on-call   | "is the API healthy right now?"                     |
| `shiftops-business.json`        | owner / ops manager   | "is operational discipline trending the right way?" |

## Why dashboards as JSON

Both files are exported via Grafana's **Share → Export → "Save to file"**
flow with the *Export for sharing externally* toggle on. That switch
turns the dashboard's data-source reference into a `${DS_PROMETHEUS}`
template variable, so the same JSON imports cleanly into any Grafana
instance (Grafana Cloud free tier, self-hosted, OSS) without manual
fix-up.

We keep these in version control because:

1. **Reviewable.** Dashboards drift quickly when edited in the UI; PR
   diffs catch the drift.
2. **Reproducible.** A new staging environment imports the same panels
   in one click.
3. **No lock-in.** If we move off Grafana later we still have the
   panel taxonomy in plain JSON.

## Importing into Grafana Cloud (free tier)

1. **Create a Prometheus data source.** Grafana Cloud free tier
   includes Grafana Cloud Metrics, which speaks the Prometheus query
   protocol. Note its UID (set as `DS_PROMETHEUS` on import).
2. **Configure scraping.** Add a scrape job that hits the API's
   `/metrics` endpoint:

   ```yaml
   # grafana-agent / alloy / vmagent — pick your favourite.
   scrape_configs:
     - job_name: shiftops-api
       scrape_interval: 30s
       metrics_path: /metrics
       static_configs:
         - targets: ["api.shiftops.example:443"]
           labels:
             env: production
   ```

3. **Import the dashboards.** Grafana → *Dashboards → Import → Upload
   JSON*, repeat for each `*.json` in this folder. When prompted,
   select the data source from step 1.

## Editing flow

Edit in Grafana, then re-export to JSON via *Share → Export → Save to
file → Export for sharing externally*. Drop the file back into this
folder and commit. The `__inputs`, `__elements`, and `__requires`
preamble must stay; that's what makes the file portable.
