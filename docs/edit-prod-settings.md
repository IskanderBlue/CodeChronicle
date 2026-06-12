Download bundle.

```
gcloud secrets versions access latest --secret=app_runtime_secrets --project=codechronicle-487104 > bundle.json
```

Edit bundle.json — e.g. add:

```
  "STRIPE_LIVE_SECRET_KEY": "sk_live_...",
  "STRIPE_PRO_PRICE_ID": "price_..."     <- the price_ ID, not prod_
```

Upload bundle, delete local copy:

```
gcloud secrets versions add app_runtime_secrets --data-file=bundle.json --project=codechronicle-487104
del bundle.json   # don't leave live keys sitting on disk
```

Restart:

```
gcloud compute ssh codechroniclenet-vm --zone=us-central1-a --project=codechronicle-487104 --tunnel-through-iap --command="sudo docker restart codechroniclenet-web"
```
