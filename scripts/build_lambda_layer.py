import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.config.settings import PROJECT_ROOT

LAYER_PACKAGES = [
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "scipy>=1.13.0",
    "scikit-learn>=1.4.0",
    "lightgbm>=4.0.0",
    "joblib>=1.3.0",
    "yfinance>=0.2.38,<1.0.0",
    "pydantic>=2.7.0",
]


def prune_layer_directory(root: Path) -> None:
    """Remove test suites, docs, caches, Cython source and dist-info to meet Lambda 250MB limit."""
    skip_dirs = ("tests", "test", "__pycache__", "idle_test")
    skip_exts = (
        ".pyc",
        ".pyo",
        ".d.ts",
        ".exe",
        ".bat",
        ".pyi",
        ".h",
        ".hpp",
        ".pyx",
        ".pxi",
        ".pxd",
        ".c",
        ".cpp",
        ".md",
        ".rst",
        ".markdown",
        ".ipynb",
    )

    for dp, dns, fns in list(os.walk(root, topdown=False)):
        for d in list(dns):
            if d in skip_dirs or d.endswith((".dist-info", ".egg-info")):
                shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
        for f in fns:
            if f.endswith(skip_exts):
                try:
                    os.remove(os.path.join(dp, f))
                except OSError:
                    pass


def build_ml_dependencies_layer(
    output_zip: Optional[Path] = None,
    build_dir: Optional[Path] = None,
    clean: bool = True,
) -> Path:
    """Build a reproducible Lambda Layer zip containing ML & data dependencies for
    Python 3.12 x86_64.
    """
    out_zip = output_zip or (PROJECT_ROOT / "artifacts" / "layers" / "ml_dependencies_layer.zip")
    b_dir = build_dir or (PROJECT_ROOT / "artifacts" / "layers" / "build")
    python_site = b_dir / "python"

    if clean and b_dir.exists():
        shutil.rmtree(b_dir, ignore_errors=True)

    python_site.mkdir(parents=True, exist_ok=True)
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    sys.stdout.write("[build_layer] Installing dependencies for manylinux_2_28_x86_64 cp312...\n")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--platform",
        "manylinux_2_28_x86_64",
        "--platform",
        "manylinux_2_17_x86_64",
        "--platform",
        "manylinux2014_x86_64",
        "--target",
        str(python_site),
        "--implementation",
        "cp",
        "--python-version",
        "3.12",
        "--only-binary=:all:",
        *LAYER_PACKAGES,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"[build_layer] Error installing wheels: {proc.stderr}\n")
        raise RuntimeError(f"pip install failed with code {proc.returncode}: {proc.stderr}")

    sys.stdout.write(
        "[build_layer] Pruning test and dist-info files to fit uncompressed limits...\n"
    )
    prune_layer_directory(python_site)

    # Provide libgomp.so.1 for LightGBM OpenMP support in Lambda
    lib_dir = b_dir / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    gomp_candidates = list(python_site.glob("**/libgomp*.so*"))
    if gomp_candidates:
        shutil.copy2(gomp_candidates[0], lib_dir / "libgomp.so.1")
        sys.stdout.write(
            f"[build_layer] Bundled libgomp.so.1 from {gomp_candidates[0].name}\n"
        )

    # Compute uncompressed size
    uncompressed_bytes = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fns in os.walk(b_dir)
        for f in fns
    )
    uncompressed_mb = uncompressed_bytes / (1024 * 1024)
    sys.stdout.write(
        f"[build_layer] Uncompressed layer size: {uncompressed_mb:.1f} MB (Limit: 250 MB)\n"
    )
    if uncompressed_mb > 250.0:
        raise RuntimeError(
            f"Uncompressed layer size ({uncompressed_mb:.1f} MB) exceeds AWS Lambda 250 MB limit."
        )

    sys.stdout.write(f"[build_layer] Creating archive {out_zip}...\n")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for dp, _, fns in os.walk(b_dir):
            for f in fns:
                full = Path(dp) / f
                rel = full.relative_to(b_dir)
                zf.write(full, rel.as_posix())

    zipped_mb = out_zip.stat().st_size / (1024 * 1024)
    sys.stdout.write(
        f"[build_layer] Layer package successfully built: {zipped_mb:.1f} MB -> {out_zip}\n"
    )
    return out_zip


def publish_ml_dependencies_layer(
    lambda_client: Any,
    s3_client: Any,
    bucket_name: str,
    layer_name: str = "idx-ml-dependencies-staging",
    layer_zip_path: Optional[Path] = None,
    dry_run: bool = False,
) -> str:
    """Upload layer to S3 and publish AWS Lambda LayerVersion."""
    zip_path = layer_zip_path or (
        PROJECT_ROOT / "artifacts" / "layers" / "ml_dependencies_layer.zip"
    )
    if not zip_path.is_file():
        raise FileNotFoundError(
            f"Layer zip not found at {zip_path}. Run build_ml_dependencies_layer first."
        )

    # Calculate SHA256 of zip
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    s3_key = f"layers/{layer_name}_{sha256[:12]}.zip"

    if dry_run:
        sys.stdout.write(f"[DRY-RUN] Upload layer to s3://{bucket_name}/{s3_key}\n")
        sys.stdout.write(f"[DRY-RUN] Publish layer version: {layer_name}\n")
        return f"arn:aws:lambda:ap-southeast-3:436095651956:layer:{layer_name}:1"

    # Check if S3 object already exists
    upload_needed = True
    try:
        s3_client.head_object(Bucket=bucket_name, Key=s3_key)
        sys.stdout.write(
            f"[publish_layer] S3 layer package already uploaded at s3://{bucket_name}/{s3_key}\n"
        )
        upload_needed = False
    except Exception:
        pass

    if upload_needed:
        sys.stdout.write(f"[publish_layer] Uploading layer zip to s3://{bucket_name}/{s3_key}...\n")
        s3_client.upload_file(str(zip_path), bucket_name, s3_key)
        sys.stdout.write("[publish_layer] Upload complete.\n")

    sys.stdout.write(f"[publish_layer] Publishing Lambda layer version {layer_name}...\n")
    layer_desc = (
        "ML and Data dependencies for BEI Stock Signal AI "
        "(pandas, numpy, scipy, sklearn, lightgbm, yfinance)"
    )
    resp = lambda_client.publish_layer_version(
        LayerName=layer_name,
        Description=layer_desc,
        Content={"S3Bucket": bucket_name, "S3Key": s3_key},
        CompatibleRuntimes=["python3.12"],
        CompatibleArchitectures=["x86_64"],
    )
    layer_arn = str(resp["LayerVersionArn"])
    sys.stdout.write(f"[publish_layer] Published layer version: {layer_arn}\n")
    return layer_arn


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and publish AWS Lambda ML dependencies layer."
    )
    parser.add_argument(
        "--bucket", default="idx-stock-signal-436095651956-data", help="Target S3 bucket"
    )
    parser.add_argument("--region", default="ap-southeast-3", help="AWS region")
    parser.add_argument(
        "--layer-name", default="idx-ml-dependencies-staging", help="Lambda layer name"
    )
    parser.add_argument("--publish", action="store_true", help="Publish layer to AWS")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions")
    args = parser.parse_args(argv)

    zip_path = build_ml_dependencies_layer()

    if args.publish:
        import boto3

        session = boto3.Session(region_name=args.region)
        lam = session.client("lambda")
        s3 = session.client("s3")
        publish_ml_dependencies_layer(
            lambda_client=lam,
            s3_client=s3,
            bucket_name=args.bucket,
            layer_name=args.layer_name,
            layer_zip_path=zip_path,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
