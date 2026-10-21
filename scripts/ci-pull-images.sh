#!/usr/bin/env bash
# CI only: pull official Docker Library base images without depending on one registry.
#
#   scripts/ci-pull-images.sh public.ecr.aws/docker/library/<name>:<tag> ...
#
# Each image is pulled from its canonical ECR Public name first. If ECR refuses
# (e.g. "toomanyrequests: Data limit exceeded" for anonymous pulls on shared
# runners), the SAME official image is pulled from Google's Docker Hub mirror,
# then Docker Hub, and re-tagged with the canonical name, so Dockerfiles, compose
# files and `docker run` use it unchanged (they never re-pull a local image).
# When ECR still answers metadata requests, the fallback is pulled by ECR's exact
# index digest, so the bytes are identical to what ECR would have served.
set -euo pipefail

pull() { # pull <ref>: a few quick attempts against one registry
  local n
  for n in 1 2 3; do
    if docker pull -q "$1" >/dev/null 2>&1; then return 0; fi
    sleep $((n * 5))
  done
  return 1
}

for canonical in "$@"; do
  case "$canonical" in
    public.ecr.aws/docker/library/*:*) ;;
    *) echo "not an official Docker Library ECR reference: $canonical" >&2; exit 2 ;;
  esac
  name_tag="${canonical#public.ecr.aws/docker/library/}"
  if pull "$canonical"; then
    echo "pulled $canonical"
    continue
  fi
  digest="$(timeout 60 docker buildx imagetools inspect "$canonical" --format '{{.Manifest.Digest}}' 2>/dev/null || true)"
  pulled=""
  for mirror in mirror.gcr.io/library docker.io/library; do
    if [[ "$digest" == sha256:* ]]; then
      src="$mirror/${name_tag%%:*}@$digest"
    else
      src="$mirror/$name_tag"
    fi
    if pull "$src"; then
      docker tag "$src" "$canonical"
      echo "pulled $canonical from $src (ECR Public unavailable)"
      pulled=1
      break
    fi
  done
  [[ -n "$pulled" ]] || { echo "could not pull $canonical from any registry" >&2; exit 1; }
done
