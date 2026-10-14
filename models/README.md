# Models

Model files are not in git. `python -m models.download` fetches them into
`$KIOSK_MODELS_DIR` (default `./models`) and checks them against `checksums.sha256`.

The first time, on a trusted network, run with `--record` and commit the updated
`checksums.sha256`. FastEmbed downloads its own model into `<models>/fastembed`
the first time the knowledge base starts.
