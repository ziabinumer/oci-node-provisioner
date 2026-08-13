import oci
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# HELPERS
# ============================================================

def log(message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def fail(message):
    log(f"CRITICAL ERROR: {message}")
    raise SystemExit(1)


# ============================================================
# ENVIRONMENT
# ============================================================

required_vars = [
    "OCI_USER_ID",
    "OCI_PRIVATE_KEY",
    "OCI_FINGERPRINT",
    "OCI_TENANCY_ID",
    "OCI_COMPARTMENT_ID",
    "OCI_REGION",
    "OCI_SUBNET_ID",
    "OCI_PUBLIC_SSH_KEY",
]

missing = [
    name for name in required_vars
    if not os.getenv(name)
]

if missing:
    fail(
        "Missing environment variables: "
        + ", ".join(missing)
    )


# ============================================================
# OCI CONFIG
# ============================================================

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION"),
}

TENANCY_ID = os.getenv("OCI_TENANCY_ID")
COMPARTMENT_ID = os.getenv("OCI_COMPARTMENT_ID")
SUBNET_ID = os.getenv("OCI_SUBNET_ID")
PUBLIC_SSH_KEY = os.getenv("OCI_PUBLIC_SSH_KEY").strip()

INSTANCE_NAME = "FX-Backend-Server"

SHAPE = "VM.Standard.A1.Flex"
OCPUS = 1
MEMORY_GB = 6
BOOT_VOLUME_GB = 50

# How long to wait after all 3 ADs fail
RETRY_DELAY = 60

# HTTP timeout for OCI requests
OCI_TIMEOUT = 30


# ============================================================
# CLIENTS
# ============================================================

log("Initializing OCI clients...")

try:
    compute_client = oci.core.ComputeClient(
        config,
        timeout=OCI_TIMEOUT
    )

    identity_client = oci.identity.IdentityClient(
        config,
        timeout=OCI_TIMEOUT
    )

    network_client = oci.core.VirtualNetworkClient(
        config,
        timeout=OCI_TIMEOUT
    )

    log("OCI clients initialized successfully.")
    log(f"Region: {config['region']}")
    log(f"Shape: {SHAPE}")
    log(f"OCPUs: {OCPUS}")
    log(f"Memory: {MEMORY_GB} GB")

except Exception as e:
    fail(f"OCI initialization failed: {type(e).__name__}: {e}")


# ============================================================
# SSH KEY
# ============================================================

if not PUBLIC_SSH_KEY:
    fail("OCI_PUBLIC_SSH_KEY is empty.")

log("SSH public key loaded successfully.")


# ============================================================
# AVAILABILITY DOMAINS
# ============================================================

log("Discovering availability domains...")

try:

    start = time.time()

    response = identity_client.list_availability_domains(
        compartment_id=TENANCY_ID
    )

    elapsed = time.time() - start

    ads = [ad.name for ad in response.data]

    log(
        f"Availability domains retrieved "
        f"in {elapsed:.1f}s."
    )

    if not ads:
        fail("No availability domains found.")

    for ad in ads:
        log(f"  AD: {ad}")

except Exception as e:
    fail(
        f"Failed to retrieve availability domains: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# SUBNET CHECK
# ============================================================

log("Checking subnet...")

try:

    start = time.time()

    subnet = network_client.get_subnet(
        SUBNET_ID
    ).data

    elapsed = time.time() - start

    log(f"Subnet retrieved in {elapsed:.1f}s.")
    log(f"Name: {subnet.display_name}")
    log(f"State: {subnet.lifecycle_state}")
    log(f"CIDR: {subnet.cidr_block}")

    if subnet.lifecycle_state != "AVAILABLE":
        fail(
            f"Subnet is not AVAILABLE: "
            f"{subnet.lifecycle_state}"
        )

except Exception as e:
    fail(
        f"Subnet check failed: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# FIND UBUNTU ARM IMAGE
# ============================================================

log("Searching for Ubuntu 24.04 image compatible with A1...")

try:

    start = time.time()

    response = compute_client.list_images(
        compartment_id=TENANCY_ID,
        operating_system="Canonical Ubuntu",
        operating_system_version="24.04",
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC"
    )

    elapsed = time.time() - start

    images = response.data

    log(
        f"Image search completed in {elapsed:.1f}s."
    )

except Exception as e:
    fail(
        f"Image search failed: "
        f"{type(e).__name__}: {e}"
    )


if not images:
    fail(
        "OCI returned no Ubuntu 24.04 images "
        f"compatible with {SHAPE}."
    )


available_images = [
    image
    for image in images
    if image.lifecycle_state == "AVAILABLE"
]

if not available_images:
    fail(
        "Compatible images were found, "
        "but none are AVAILABLE."
    )


selected_image = available_images[0]

IMAGE_ID = selected_image.id

log("Selected image:")
log(f"  Name: {selected_image.display_name}")
log(f"  OCID: {IMAGE_ID}")
log(f"  State: {selected_image.lifecycle_state}")


# ============================================================
# EXISTING INSTANCE CHECK
# ============================================================

log(
    f"Checking for existing instance "
    f"'{INSTANCE_NAME}'..."
)

try:

    start = time.time()

    instances = compute_client.list_instances(
        compartment_id=COMPARTMENT_ID
    ).data

    elapsed = time.time() - start

    log(
        f"Instance list retrieved in {elapsed:.1f}s."
    )

    for instance in instances:

        if instance.display_name == INSTANCE_NAME:

            log("=" * 60)
            log("INSTANCE ALREADY EXISTS")
            log(f"OCID: {instance.id}")
            log(f"State: {instance.lifecycle_state}")
            log("=" * 60)

            raise SystemExit(0)

    log("No existing instance found.")

except SystemExit:
    raise

except Exception as e:

    fail(
        f"Could not check existing instances: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# PROVISIONING
# ============================================================

attempt = 0

while True:

    # Try every AD before waiting
    for current_ad in ads:

        attempt += 1

        log("")
        log("=" * 60)
        log(f"PROVISIONING ATTEMPT #{attempt}")
        log("=" * 60)
        log(f"Availability Domain: {current_ad}")
        log(f"Shape: {SHAPE}")
        log(f"OCPUs: {OCPUS}")
        log(f"Memory: {MEMORY_GB} GB")
        log(f"Boot Volume: {BOOT_VOLUME_GB} GB")
        log("=" * 60)

        # ----------------------------------------------------
        # CREATE REQUEST
        # ----------------------------------------------------

        try:

            launch_details = (
                oci.core.models.LaunchInstanceDetails(

                    display_name=INSTANCE_NAME,

                    compartment_id=COMPARTMENT_ID,

                    availability_domain=current_ad,

                    shape=SHAPE,

                    shape_config=(
                        oci.core.models
                        .LaunchInstanceShapeConfigDetails(
                            ocpus=OCPUS,
                            memory_in_gbs=MEMORY_GB
                        )
                    ),

                    source_details=(
                        oci.core.models
                        .InstanceSourceViaImageDetails(
                            source_type="image",
                            image_id=IMAGE_ID,
                            boot_volume_size_in_gbs=(
                                BOOT_VOLUME_GB
                            )
                        )
                    ),

                    create_vnic_details=(
                        oci.core.models
                        .CreateVnicDetails(
                            subnet_id=SUBNET_ID,
                            assign_public_ip=True,
                            assign_private_dns_record=True,
                            display_name="forexalertsvnic"
                        )
                    ),

                    metadata={
                        "ssh_authorized_keys":
                            PUBLIC_SSH_KEY
                    }
                )
            )

            log(
                "Sending instance launch request "
                "to OCI..."
            )

            start = time.time()

            response = compute_client.launch_instance(
                launch_details
            )

            elapsed = time.time() - start

            instance = response.data

            log(
                f"OCI accepted request in "
                f"{elapsed:.1f}s."
            )

            log("=" * 60)
            log("INSTANCE CREATION ACCEPTED")
            log(f"OCID: {instance.id}")
            log(f"State: {instance.lifecycle_state}")
            log("=" * 60)

        # ----------------------------------------------------
        # OCI ERROR
        # ----------------------------------------------------

        except oci.exceptions.ServiceError as e:

            log("")
            log("OCI API ERROR")
            log(f"Status: {e.status}")
            log(f"Code: {e.code}")
            log(f"Message: {e.message}")

            error_text = (
                f"{e.code} {e.message}"
            ).lower()

            capacity_error = (
                "out of host capacity" in error_text
                or "out of capacity" in error_text
                or "capacity" in error_text
            )

            if capacity_error:

                log(
                    f"Capacity unavailable in "
                    f"{current_ad}."
                )

                log(
                    "Moving to next availability domain..."
                )

                continue

            fail(
                "Non-capacity OCI error encountered. "
                "Stopping."
            )

        except Exception as e:

            fail(
                f"Unexpected launch error: "
                f"{type(e).__name__}: {e}"
            )

        # ----------------------------------------------------
        # WAIT FOR RUNNING
        # ----------------------------------------------------

        log("")
        log(
            "Instance request succeeded. "
            "Waiting for RUNNING state..."
        )

        try:

            start = time.time()

            waiter = oci.wait_until(
                compute_client,

                compute_client.get_instance(
                    instance.id
                ),

                evaluate_response=lambda response:
                    response.data.lifecycle_state
                    in [
                        "RUNNING",
                        "TERMINATED"
                    ],

                max_wait_seconds=600,

                max_interval_seconds=15
            )

            elapsed = time.time() - start

            final_instance = waiter.data

            log(
                f"Instance state check completed "
                f"in {elapsed:.1f}s."
            )

            log(
                f"Final state: "
                f"{final_instance.lifecycle_state}"
            )

            if (
                final_instance.lifecycle_state
                != "RUNNING"
            ):

                fail(
                    "Instance did not reach RUNNING."
                )

        except Exception as e:

            fail(
                f"Failed while waiting for instance: "
                f"{type(e).__name__}: {e}"
            )

        # ----------------------------------------------------
        # GET VNIC
        # ----------------------------------------------------

        log("Retrieving VNIC information...")

        try:

            start = time.time()

            attachments = (
                compute_client
                .list_vnic_attachments(
                    compartment_id=COMPARTMENT_ID,
                    instance_id=instance.id
                )
                .data
            )

            if not attachments:
                fail("No VNIC attachment found.")

            vnic_id = attachments[0].vnic_id

            vnic = network_client.get_vnic(
                vnic_id
            ).data

            elapsed = time.time() - start

            log(
                f"VNIC retrieved in {elapsed:.1f}s."
            )

            log("")
            log("=" * 60)
            log("INSTANCE READY")
            log("=" * 60)
            log(f"Instance OCID: {instance.id}")
            log(f"Private IP:    {vnic.private_ip}")
            log(f"Public IP:     {vnic.public_ip}")
            log("=" * 60)

            if vnic.public_ip:

                log("")
                log("SSH:")
                log(
                    f"ssh -i ~/.ssh/id_ed25519 "
                    f"ubuntu@{vnic.public_ip}"
                )

            log("")
            log("Provisioning completed successfully.")

            raise SystemExit(0)

        except SystemExit:
            raise

        except Exception as e:

            fail(
                f"Failed retrieving VNIC: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # ALL ADS FAILED
    # ========================================================

    log("")
    log("=" * 60)
    log("ALL AVAILABILITY DOMAINS FAILED")
    log("=" * 60)

    log(
        f"Waiting {RETRY_DELAY} seconds "
        "before trying all ADs again..."
    )

    for remaining in range(RETRY_DELAY, 0, -10):

        log(
            f"Next retry in approximately "
            f"{remaining} seconds..."
        )

        time.sleep(min(10, remaining))
