# Deploying Spendcheck on the group's Ronin VM (AWS EC2) with Kubernetes

Target: **k3s** (a full, certified Kubernetes distribution) on the course's Ronin machine
`dsa2111-group14.nus.cloud`, an AWS EC2 **t3.medium** (2 vCPU, 4 GiB) in ap-southeast-1.
Docker builds the images on a laptop; Kubernetes runs them on AWS. Docker Compose stays the
local development set-up.

```
laptop (Docker)  --docker save | ssh-->  VM: Docker image store  <--  k3s (uses Docker as runtime)
                                                                         |
browser --SSH tunnel--> VM:80 Traefik Ingress --> frontend (nginx) --/api--> gateway --> modules 1-5
```

There is no container registry (no AWS account, so no ECR) and no S3: images are streamed to the
VM over SSH, and the database (with the annual reports already ingested) is copied from a laptop.
Port 80 is closed to the internet by Ronin's firewall, so the site is reached through an SSH
tunnel. That also keeps the free AI quota (50 requests/day) to ourselves.

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
# unpacked copy of every image, which does not fit on the 40 GB disk.
echo '{"features": {"containerd-snapshotter": false}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker

# k3s, using the VM's Docker as its container runtime (images are stored once)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --docker --write-kubeconfig-mode 644" sh -
kubectl get nodes
```

## 2. Ship the images (after any code change)

```bash
docker compose build
for s in extractor categoriser forecaster gateway chat-agent report-reader frontend; do
  docker tag spendcheck-$s:latest spendcheck/$s:v1
done
docker save spendcheck/{extractor,categoriser,forecaster,gateway,chat-agent,report-reader,frontend}:v1 \
  | gzip -3 | ssh -i $KEY $VM 'gunzip | docker load'
```

The first upload is about 3 GB compressed. To ship one changed service, save just that image.
Re-using the tag `v1` is fine; restart the deployment afterwards (step 6) so it picks the new
image up.

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

**Adding annual reports.** Ingest on the laptop (about 3 s a page on 2 vCPUs is too slow for the VM),
then repeat this step. The three SGX reports came from SGX Company Announcements, category "Annual
Reports and Related Documents", and are listed in `data/reports/sgx/manifest.csv`:

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm report-ingest python -m ingest.run --manifest /data/reports/sgx/manifest.csv
```

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
| `ErrImageNeverPull` / `ImagePullBackOff` | the image is not on the VM: `docker images \| grep spendcheck`, then step 2 |
| Disk full | `df -h /`; `docker image prune -f` removes old untagged images |
| Site down after the VM restarted | wait 3 minutes (the extractor loads its models), then `kubectl get pods -n spendcheck` |
| Answers fail with "Provider returned error" | a free model is down. `LLM_MODEL` in `01-configmap.yaml` is a list: OpenRouter tries each in turn. Swap in models that are up (https://openrouter.ai/models, filter "free"), `kubectl apply -k k8s/`, then restart chat-agent and report-reader |

`kubectl top pods -n spendcheck` shows live memory per module (handy for the report).
