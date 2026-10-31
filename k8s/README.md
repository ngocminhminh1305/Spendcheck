# Deploying Spendcheck on the group's Ronin VM (AWS EC2) with Kubernetes

Target: **k3s** (a full, certified Kubernetes distribution) on the course's Ronin machine
`dsa2111-group14.nus.cloud`, an AWS EC2 **t3.medium** (2 vCPU, 4 GiB, 60 GB disk) in
ap-southeast-1, with images in **Amazon ECR** and the annual-report PDFs in **Amazon S3**, both in
an AWS Academy Learner Lab account (767397718813, us-east-1). Docker builds the images on a
laptop; Kubernetes runs them on AWS. Docker Compose stays the local development set-up.

```
laptop (Docker) --push--> ECR (us-east-1) --pull once per release--> VM Docker <-- k3s (Docker runtime)
laptop ingest  <--PDFs--  S3 (us-east-1)        laptop Postgres --pg_dump/pg_restore--> VM Postgres
browser --SSH tunnel--> VM:80 Traefik Ingress --> frontend (nginx) --/api--> gateway --> modules 1-5
```

Learner Lab keys expire after a few hours, so the VM pulls each image from ECR **once**, at deploy
time, and every container uses `imagePullPolicy: Never`: Kubernetes runs that local copy and never
needs AWS credentials. Ingestion is too slow for the VM, so it runs on a laptop (reading the PDFs
from S3) and the database is copied across. Port 80 is closed to the internet by Ronin's
firewall, so the site is reached through an SSH tunnel. That also keeps the free AI quota
(50 requests/day) to ourselves.

**Learner Lab keys:** start the lab, then copy *AWS Details > AWS CLI* into `~/.aws/credentials`
(or run `aws configure export-credentials --format env` in the lab terminal). The AWS commands
below use Amazon's official AWS CLI image, so nothing needs installing:

```bash
aws() { MSYS_NO_PATHCONV=1 docker run --rm -v "$(cygpath -w ~/.aws):/root/.aws:ro" amazon/aws-cli:2.27.0 "$@"; }
REGISTRY=767397718813.dkr.ecr.us-east-1.amazonaws.com
```

All commands below run in **Git Bash from the repo root** on a laptop unless marked *on the VM*.

```bash
KEY=~/.ssh/dsa2111-g14-key.pem            # from the prof's email; only your account may read it
VM=ubuntu@dsa2111-group14.nus.cloud
```

Start the VM in the Ronin portal (https://ronin.nus.cloud, NUS login) first. It costs about
US$0.05/hour and **stops itself at 23:00 every day** (Smart Schedule, "stop only"). k3s starts on
boot, so the site is back about 3 minutes after the VM starts. Stop the VM when you finish.

## 1. One-time VM set-up (already done on 19 Oct 2026)

*On the VM:*

```bash
# 2 GB swap: the stack uses about 3.2 of the 4 GiB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-spendcheck-swap.conf

# Classic Docker storage: Docker 29's default (containerd image store) keeps a packed AND an
# unpacked copy of every image, which did not fit on the original 40 GB disk.
echo '{"features": {"containerd-snapshotter": false}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker

# k3s, using the VM's Docker as its container runtime (images are stored once)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --docker --write-kubeconfig-mode 644" sh -
kubectl get nodes
```

## 2. Ship the images through ECR (after any code change)

Build, tag and push from the laptop (about 3 minutes for all seven; use Bash, because Windows
PowerShell corrupts the login token when it pipes it):

```bash
docker compose build
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $REGISTRY
for s in extractor categoriser forecaster gateway chat-agent report-reader frontend; do
  docker tag spendcheck-$s:latest $REGISTRY/spendcheck/$s:v1
  docker push $REGISTRY/spendcheck/$s:v1
done
```

Then pull them onto the VM once (about 4 minutes). The 12-hour login token is passed over SSH and
the VM logs out of ECR straight afterwards:

```bash
aws ecr get-login-password --region us-east-1 | ssh -i $KEY $VM "docker login --username AWS --password-stdin $REGISTRY && \
  for s in extractor categoriser forecaster gateway chat-agent report-reader frontend; do docker pull -q $REGISTRY/spendcheck/\$s:v1; done; \
  docker logout $REGISTRY"
```

Re-using the tag `v1` is fine: after pulling, restart each changed deployment so it picks the new
image up (`kubectl rollout restart deployment/<name> -n spendcheck`, on the VM).

## 3. Ship the manifests and the database schema

```bash
tar -cf - --exclude=secrets.env k8s db/init | ssh -i $KEY $VM 'mkdir -p ~/spendcheck && tar -xf - -C ~/spendcheck'
```

## 4. Secrets (once)

*On the VM:* create `~/spendcheck/k8s/secrets.env` from `secrets.env.example`, with long random
passwords (letters and digits only) and the OpenRouter key, then `chmod 600` it. Everyone in the
group shares the `ubuntu` login, so everyone can read it: never put a personal paid key here.

## 5. Deploy

*On the VM:*

```bash
cd ~/spendcheck
kubectl apply -f k8s/00-namespace.yaml
kubectl create configmap db-init --from-file=db/init -n spendcheck --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k k8s/
kubectl get pods -n spendcheck -w        # all Running and 1/1 READY after 1-3 minutes
```

## 6. Copy the data (once, or to reset the demo)

The schema comes from `db/init`; the rows (demo user, transactions, budgets, ingested reports)
come from a laptop where `docker compose` has them:

```bash
docker compose exec -T postgres pg_dump -U postgres -d spendcheck --data-only -Fc > spendcheck-data.dump
scp -i $KEY spendcheck-data.dump $VM:spendcheck/
```

*On the VM:*

```bash
cd ~/spendcheck
kubectl exec -i -n spendcheck postgres-0 -- psql -U postgres -d spendcheck -v ON_ERROR_STOP=1 -c \
  "TRUNCATE users, categories, transactions, budgets, reports.documents, reports.chunks RESTART IDENTITY CASCADE"
kubectl exec -i -n spendcheck postgres-0 -- pg_restore -U postgres -d spendcheck --data-only --disable-triggers < spendcheck-data.dump
```

After shipping a new image: `kubectl rollout restart deployment/<name> -n spendcheck`.

**Adding annual reports.** The PDFs live in the private bucket `spendcheck-reports-767397718813`
(`manifest.csv` at the top lists every report; `sgx/` and `financebench/` hold the files). Upload
a new PDF, add a line to the manifests, ingest on the laptop from S3 (about 3 s a page, too slow for
the VM), then repeat this step to copy the database:

```bash
aws s3 cp new-report.pdf s3://spendcheck-reports-767397718813/sgx/
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$(cygpath -w ~/.aws):/aws-creds:ro" \
  -e AWS_SHARED_CREDENTIALS_FILE=/aws-creds/credentials -e AWS_DEFAULT_REGION=us-east-1 \
  report-ingest python -m ingest.run --manifest s3://spendcheck-reports-767397718813/manifest.csv
```

Reports already in the database are skipped. The three SGX reports came from SGX Company
Announcements, category "Annual Reports and Related Documents" (sources in
`data/reports/README.md`).

## 7. Open the website

```bash
ssh -i $KEY -N -L 8080:localhost:80 $VM
```

Leave that running and open http://localhost:8080. The M1-M5 dots at the top should all be green.

## Troubleshooting

| Symptom | Check |
|---|---|
| A pod is `Pending` | `kubectl describe pod <pod> -n spendcheck`: usually not enough memory; `free -h` |
| A pod restarts (`CrashLoopBackOff`, `OOMKilled`) | `kubectl logs <pod> -n spendcheck --previous` |
| `ErrImageNeverPull` / `ImagePullBackOff` | the image is not on the VM: `docker images \| grep spendcheck`, then pull it from ECR (step 2) |
| Every pod `Pending` or `ContainerStatusUnknown`; node tainted `disk-pressure` | the disk passed 85%: Kubernetes evicted the pods and **deleted their images**. Free space (`df -h /`; download caches such as `~/.cache/pip` are safe to clear), pull the images from ECR again (step 2), then `kubectl delete pods -n spendcheck --field-selector=status.phase=Failed`. This happened on 26 Oct when other work filled the disk; it was grown to 60 GB afterwards. Please do not build or run the project with docker compose on the VM |
| New pod stuck `Pending` with "Insufficient memory" during a rollout | an old broken pod still reserves memory: delete the old ReplicaSet (`kubectl get rs -n spendcheck`, then `kubectl delete rs <old>`) |
| Site down after the VM restarted | wait 3 minutes (the extractor loads its models), then `kubectl get pods -n spendcheck` |
| Answers fail with "Provider returned error" | a free model is down. `LLM_MODEL` in `01-configmap.yaml` is a list: OpenRouter tries each in turn. Swap in models that are up (https://openrouter.ai/models, filter "free"), `kubectl apply -k k8s/`, then restart chat-agent and report-reader |

`kubectl top pods -n spendcheck` shows live memory per module (handy for the report).
