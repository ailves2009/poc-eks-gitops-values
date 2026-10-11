# poc-eks-gitops-values

**With which parameters.** Environment values for everything Argo CD deploys; the charts live in
[poc-aws-eks-karpenter/charts](https://github.com/ailves2009/poc-aws-eks-karpenter/tree/master/charts),
the ApplicationSets in [poc-eks-gitops-root](https://github.com/ailves2009/poc-eks-gitops-root).

## Layout

```text
infra/<cluster>/<component>.yaml        values for an infra component (chart pinned in the root repo)
workloads/<env>/<app>/_env.yaml         landscape values, given to every service of <app> in <env>
workloads/<env>/<app>/<service>.yaml    one service: chart + tag, image by digest, HPA, ingress, placement
scripts/render_all.py                   CI: render every file exactly as Argo CD does
```

Environments are directories, not repositories (`workloads/dev/…`, later `workloads/staging/…`).

## One service file = one Application

The workloads ApplicationSet turns `workloads/dev/demo/nginx.yaml` into Application
`demo-dev-nginx` in namespace `demo-dev`, project `demo`, rendering:

```text
charts/demo-apps @ chart.revision            (git tag of poc-aws-eks-karpenter)
  values.yaml                  chart: shared shape
  values/nginx.yaml            chart: nginx's shape
  workloads/dev/demo/_env.yaml this repo: landscape
  workloads/dev/demo/nginx.yaml this repo: the service      ← later wins
  activeApp=nginx              Helm parameter
```

Adding a service: its shape in the chart, then one file here. No ApplicationSet change.

## Rules

- **`chart.path` and `chart.revision` are required** in every service file. Bumping `revision`
  rolls a new chart version out to that service only.
- **Images by digest**: `image.repository`, `image.tag` (for humans) and `image.digest` (what the
  kubelet pulls). The chart's `values.schema.json` rejects an image without a digest.
- **Unknown keys fail.** Every file here is an ordinary Helm values file, validated by the
  chart's schema (`additionalProperties: false`): a typo fails the render instead of falling
  back to a default.
- `_env.yaml` is never a service: the generator excludes it.

## CI

`scripts/render_all.py` renders every service file with the chart tag it names and every infra
component with the chart version pinned in the root repo, then runs `kubeconform -strict`.
Local run against an unpushed chart tag:

```bash
CHARTS_REPO=/path/to/poc-aws-eks-karpenter python3 scripts/render_all.py . ../poc-eks-gitops-root
```
