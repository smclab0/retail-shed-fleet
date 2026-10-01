# retail-shed-fleet

GitOps for the stores of [retail-shed](https://github.com/smclab0/hypothetical-retail-edge),
a SUSE Edge retail lab: Rancher Prime at HQ, K3s store clusters on SL Micro.
Fleet deploys **store-pos**, a small till app, to every store from this repo.

```
app/                     store-pos source (Python stdlib + SQLite on SUSE BCI Python)
  VERSION                image version; bump it to release
.github/workflows/       builds ghcr.io/smclab0/store-pos:<VERSION> on push to main
fleet/gitrepo.yaml       the Fleet GitRepo to create in Rancher (fleet-default)
fleet/store-pos/         the Fleet bundle: fleet.yaml + Helm chart
```

## What runs in a store

| | All stores | Flagship (`retail.lab/tier=flagship`) |
|---|---|---|
| Till (`/`) | ✓ | ✓ |
| Click & collect board (`/collect/`) | | ✓ |

- **Identity from cluster labels.** `fleet.yaml` fills `store.id`, `store.region` and `store.tier`
  from each cluster's `retail.lab/*` labels, which HQ sets when it creates the store record.
  One bundle serves the whole estate.
- **Regional pricing.** `targetCustomizations` select clusters by `retail.lab/region`.
  London gets a 1.12 price multiplier and a banner; Edinburgh gets its own banner.
  Everyone else uses the default price list in `chart/values.yaml`. The first matching
  customization wins.
- **Trades offline.** The till records sales in SQLite on a local-path volume. It probes
  HQ (`rancher.retail-shed.local/ping`) every 10 s and shows **HQ online** or **HQ offline -
  trading locally**. Sales made while offline are counted. Try it with
  `./wan.sh outage <store>` in the lab repo.

## Deploy to the stores

On the Rancher cluster:

```bash
kubectl apply -f fleet/gitrepo.yaml
```

Or in the Rancher UI: **Continuous Delivery → Git Repos → Add Repository**, workspace
`fleet-default`, with this repo's URL, branch `main` and path `fleet/store-pos`. Fleet polls
every 30 s.

The store LANs are only routed on vrack0. To open a till from a workstation:

```bash
ssh -L 8080:10.120.3.11:80 root@172.16.0.69   # man-001; then http://localhost:8080/
ssh -L 8081:10.120.1.11:80 root@172.16.0.69   # lon-001 flagship; /collect/ for the board
```

## Releasing a new version

1. Change `app/`, bump `app/VERSION` and push. The workflow publishes
   `ghcr.io/smclab0/store-pos:<VERSION>`.
2. Set `image.tag` in `fleet/store-pos/chart/values.yaml` to the new version and push.
   Fleet rolls it out to every store.

To canary one store first, add a `targetCustomization` above the regional ones, for example
`matchLabels: {retail.lab/store: man-001}` with `helm.values.image.tag: <new>`. Once it looks
good, promote the tag in `values.yaml` and remove the canary.

## Run locally

```bash
docker build -t store-pos app
docker run --rm -p 8080:8080 -e STORE_ID=test -e DB_FILE=/tmp/store.db store-pos
```
