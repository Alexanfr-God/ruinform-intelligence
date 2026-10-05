# RUINFORM NFT Media Contract v1

Status: DEVNET acceptance contract. Mainnet remains gated until final media/storage audit.

## Purpose

Every RUINFORM NFT must have a deterministic marketplace face that renders predictably in wallets, explorers and marketplaces. The primary image is a finished collectible asset, never a browser screenshot, uncropped DOM canvas, source render, or SVG-only dependency.

## Identity NFT — RUI ID

- Primary media: raster image.
- Current Devnet target: **1600 × 1600 px**.
- Aspect ratio: **1:1**.
- MIME: `image/png`.
- No external padding or browser/viewer background baked into the file.
- The exported image must match the visible RUINFORM ID dossier.
- The upload endpoint rejects any PNG whose IHDR dimensions are not exactly 1600 × 1600.

Metadata requirements:

```json
{
  "name": "RUINFORM ID · RUI-000003",
  "description": "...",
  "image": "https://.../identity.png",
  "category": "image",
  "properties": {
    "category": "image",
    "files": [
      { "uri": "https://.../identity.png", "type": "image/png" }
    ]
  }
}
```

## Artifact Passport NFT

- Primary marketplace media: **1600 × 2000 px PNG**.
- Aspect ratio: **4:5**.
- MIME: `image/png`.
- Primary image is the designed RUINFORM Artifact Passport / certificate, not the raw object render.
- SVG may exist only as a secondary master/vector file.
- The PNG is generated and sealed **before** the mint intent.
- SHA-256 of the PNG is written into the canonical mint snapshot.
- The upload endpoint rejects files that are not exact 1600 × 2000 PNGs.

Metadata requirements:

```json
{
  "name": "...",
  "description": "...",
  "image": "https://.../artifact-passport.png",
  "category": "image",
  "properties": {
    "category": "image",
    "files": [
      { "uri": "https://.../artifact-passport.png", "type": "image/png" },
      { "uri": "https://.../artifact-passport.svg", "type": "image/svg+xml" }
    ],
    "media_standard": "RF-NFT-MEDIA-v1",
    "media_sha256": "...",
    "media_dimensions": "1600x2000"
  }
}
```

## Immutability rule

For a new Artifact Passport the primary image URL and the image SHA-256 are part of the canonical snapshot before the Core Asset is minted. Changing the primary image therefore changes the canonical snapshot hash and is not the same certificate.

## Marketplace rule

`metadata.image` is always the marketplace/wallet fallback image. `properties.files[0]` must point to the same primary raster image with the correct MIME type. Secondary assets must never replace the primary image.

## Devnet acceptance gate

Before promoting the media contract:

1. Mint a fresh RUI ID and confirm its primary media is exact 1:1 with no external canvas.
2. Mint a fresh Artifact Passport and confirm its primary media is exact 4:5 PNG.
3. Confirm metadata `image`, top-level `category`, `properties.category`, and `properties.files` agree.
4. Inspect the same assets independently in Solana Explorer and a Metaplex Core-compatible viewer.
5. Confirm the Artifact snapshot contains `artifact_image_sha256` and `nft_media_standard=RF-NFT-MEDIA-v1`.

## Mainnet gate

Mainnet is the final stage. Before Mainnet, primary images and metadata JSON must be moved to permanent/content-addressed storage (for example Arweave/Irys or an equivalent audited immutable store), and file-size optimization must be validated for wallet/marketplace delivery. HTTP/R2 Devnet URLs are not considered the final Mainnet permanence layer.
