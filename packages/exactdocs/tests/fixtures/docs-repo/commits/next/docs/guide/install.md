---
title: Installing Acme Payments
description: Install the Acme Payments SDK with Docker or from source.
tags: [guide, install]
---

# Guide

Everything you need to get the SDK running.

## Install

Acme Payments needs Python 3.12 or newer.

| Platform | Supported | Notes                   |
| -------- | --------- | ----------------------- |
| Linux    | yes       | x86-64 and ARM64        |
| macOS    | yes       | Apple silicon and Intel |
| Windows  | partial   | use WSL                 |

### Docker

Pull the image and start the sandbox. Images are published for every release:

```bash
docker pull acme/payments:1.4
docker run --rm -p 8080:8080 acme/payments:1.4
```

#### Troubleshooting

If the port is taken, pick another one with `-p 9090:8080`.

### Podman

The image also runs rootless:

```bash
podman run --rm -p 8080:8080 acme/payments:2.0-rc1
```

### From source

Clone the repository and install it in editable mode:

```bash
git clone https://example.invalid/acme/payments.git
pip install -e payments
```

#### Troubleshooting

Make sure `pip --version` reports Python 3.12 or newer.
