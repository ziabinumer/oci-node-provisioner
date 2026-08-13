import oci
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# LOGGING
# ============================================================

def log(message):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{timestamp}] {message}", flush=True)


def fatal(message):
    log(f"CRITICAL ERROR: {message}")
    raise SystemExit(1)


# ============================================================
# ENVIRONMENT VARIABLES
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
    fatal(
        "Missing environment variables:\n"
        + "\n".join(f"  - {name}" for name in missing)
    )


# ============================================================
# OCI CONFIGURATION
# ============================================================

TENANCY_ID = os.getenv("OCI_TENANCY_ID")
COMPARTMENT_ID = os.getenv("OCI_COMPARTMENT_ID")
SUBNET_ID = os.getenv("OCI_SUBNET_ID")
PUBLIC_SSH_KEY = os.getenv("OCI_PUBLIC_SSH_KEY").strip()

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": TENANCY_ID,
    "region": os.getenv("OCI_REGION"),
}


# ============================================================
# INSTANCE CONFIGURATION
# ============================================================

INSTANCE_NAME = "FX-Backend-Server"

SHAPE = "VM.Standard.A1.Flex"
OCPUS = 1
MEMORY_GB = 6
BOOT_VOLUME_GB = 50

OS_NAME = "Canonical Ubuntu"
OS_VERSION = "24.04"

# 30 seconds prevents a request from appearing frozen
OCI_TIMEOUT = 30


# ============================================================
# START
# ============================================================

log("=" * 60)
log("OCI A1 PROVISIONER")
log("=" * 60)

log(f"Region:          {config['region']}")
log(f"Shape:           {SHAPE}")
log(f"OCPUs:           {OCPUS}")
log(f"Memory:          {MEMORY_GB} GB")
log(f"Boot Volume:     {BOOT_VOLUME_GB} GB")
log(f"Instance Name:   {INSTANCE_NAME}")
log("=" * 60)


# ============================================================
# INITIALIZE OCI CLIENTS
# ============================================================

try:

    log("Initializing OCI clients...")

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

    log("OCI authentication successful.")

except Exception as e:

    fatal(
        f"OCI initialization failed: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# SSH KEY
# ============================================================

if not PUBLIC_SSH_KEY:
    fatal("OCI_PUBLIC_SSH_KEY is empty.")

log("SSH public key loaded successfully.")


# ============================================================
# AVAILABILITY DOMAINS
# ============================================================

log("")
log("Discovering availability domains...")

try:

    response = identity_client.list_availability_domains(
        compartment_id=TENANCY_ID
    )

    ads = [ad.name for ad in response.data]

    if not ads:
        fatal("No availability domains were returned.")

    log("Available availability domains:")

    for ad in ads:
        log(f"  - {ad}")

except Exception as e:

    fatal(
        f"Failed to retrieve availability domains: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# VERIFY SUBNET
# ============================================================

log("")
log("Checking subnet...")

try:

    subnet = network_client.get_subnet(
        SUBNET_ID
    ).data

    log(f"Name:   {subnet.display_name}")
    log(f"State:  {subnet.lifecycle_state}")
    log(f"CIDR:   {subnet.cidr_block}")

    if subnet.lifecycle_state != "AVAILABLE":
        fatal(
            f"Subnet is not AVAILABLE. "
            f"Current state: {subnet.lifecycle_state}"
        )

    log("Subnet access: OK")

except oci.exceptions.ServiceError as e:

    fatal(
        f"Cannot access subnet.\n"
        f"Status: {e.status}\n"
        f"Code: {e.code}\n"
        f"Message: {e.message}"
    )

except Exception as e:

    fatal(
        f"Subnet check failed: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# FIND COMPATIBLE UBUNTU IMAGE
# ============================================================

log("")
log("=" * 60)
log("SEARCHING FOR UBUNTU 24.04 IMAGE")
log("=" * 60)

try:

    log(
        f"Looking for {OS_NAME} {OS_VERSION} "
        f"compatible with {SHAPE}..."
    )

    response = compute_client.list_images(
        compartment_id=TENANCY_ID,
        operating_system=OS_NAME,
        operating_system_version=OS_VERSION,
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC"
    )

    images = response.data

except oci.exceptions.ServiceError as e:

    fatal(
        f"Image search failed.\n"
        f"Status: {e.status}\n"
        f"Code: {e.code}\n"
        f"Message: {e.message}"
    )

except Exception as e:

    fatal(
        f"Image search failed: "
        f"{type(e).__name__}: {e}"
    )


if not images:

    fatal(
        f"No {OS_NAME} {OS_VERSION} image was returned "
        f"for shape {SHAPE}."
    )


available_images = [
    image
    for image in images
    if image.lifecycle_state == "AVAILABLE"
]


if not available_images:

    fatal(
        "Compatible images were found, "
        "but none are AVAILABLE."
    )


# Newest image is first because of TIMECREATED DESC
selected_image = available_images[0]

IMAGE_ID = selected_image.id


log("")
log("Selected image:")
log(f"  Name:    {selected_image.display_name}")
log(f"  OCID:    {IMAGE_ID}")
log(f"  State:   {selected_image.lifecycle_state}")
log(f"  OS:      {selected_image.operating_system}")
log(
    f"  Version: "
    f"{selected_image.operating_system_version}"
)


# ============================================================
# CHECK EXISTING INSTANCE
# ============================================================

log("")
log(
    f"Checking for existing instance "
    f"'{INSTANCE_NAME}'..."
)

try:

    instances = compute_client.list_instances(
        compartment_id=COMPARTMENT_ID
    ).data

    existing_instance = None

    for instance in instances:

        if instance.display_name == INSTANCE_NAME:

            existing_instance = instance
            break

    if existing_instance:

        log("")
        log("=" * 60)
        log("INSTANCE ALREADY EXISTS")
        log("=" * 60)
        log(f"OCID:  {existing_instance.id}")
        log(f"State: {existing_instance.lifecycle_state}")
        log("=" * 60)

        raise SystemExit(0)

    log("No existing instance found.")

except SystemExit:
    raise

except oci.exceptions.ServiceError as e:

    fatal(
        f"Cannot list instances.\n"
        f"Status: {e.status}\n"
        f"Code: {e.code}\n"
        f"Message: {e.message}"
    )

except Exception as e:

    fatal(
        f"Instance check failed: "
        f"{type(e).__name__}: {e}"
    )


# ============================================================
# PROVISIONING
# ============================================================

log("")
log("=" * 60)
log("STARTING CAPACITY ATTEMPTS")
log("=" * 60)

# Only try the ADs returned by OCI.
# We normally expect 3 in Frankfurt.
for attempt, current_ad in enumerate(ads, start=1):

    log("")
    log("=" * 60)
    log(f"ATTEMPT {attempt}/{len(ads)}")
    log("=" * 60)
    log(f"Availability Domain: {current_ad}")
    log(f"Shape:              {SHAPE}")
    log(f"OCPUs:              {OCPUS}")
    log(f"Memory:             {MEMORY_GB} GB")
    log(f"Boot Volume:        {BOOT_VOLUME_GB} GB")
    log("=" * 60)

    try:

        # ----------------------------------------------------
        # BUILD INSTANCE REQUEST
        # ----------------------------------------------------

        launch_details = oci.core.models.LaunchInstanceDetails(

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
                    boot_volume_size_in_gbs=BOOT_VOLUME_GB
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
                "ssh_authorized_keys": PUBLIC_SSH_KEY
            }
        )


        # ----------------------------------------------------
        # SEND REQUEST
        # ----------------------------------------------------

        log("Sending launch request to OCI...")

        start_time = time.time()

        response = compute_client.launch_instance(
            launch_details
        )

        elapsed = time.time() - start_time

        instance = response.data

        log(
            f"OCI accepted the request "
            f"in {elapsed:.1f} seconds."
        )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        log("")
        log("=" * 60)
        log("SUCCESS — INSTANCE CREATION STARTED")
        log("=" * 60)
        log(f"Instance OCID: {instance.id}")
        log(f"State:         {instance.lifecycle_state}")
        log(f"AD:            {current_ad}")
        log("=" * 60)

        log("")
        log(
            "OCI is now creating the instance."
        )

        log(
            "The GitHub Actions job will exit now."
        )

        raise SystemExit(0)


    # ========================================================
    # OCI SERVICE ERROR
    # ========================================================

    except oci.exceptions.ServiceError as e:

        log("")
        log("OCI API ERROR")
        log(f"Status:  {e.status}")
        log(f"Code:    {e.code}")
        log(f"Message: {e.message}")

        error_text = (
            f"{e.code} {e.message}"
        ).lower()


        # ----------------------------------------------------
        # CAPACITY ERROR
        # ----------------------------------------------------

        capacity_error = (
            "out of host capacity" in error_text
            or "out of capacity" in error_text
            or "capacity" in error_text
        )

        if capacity_error:

            log("")
            log(
                f"No A1 capacity available in "
                f"{current_ad}."
            )

            if attempt < len(ads):

                log(
                    "Trying the next availability domain..."
                )

                continue

            else:

                log("")
                log("=" * 60)
                log("NO A1 CAPACITY AVAILABLE")
                log("=" * 60)
                log(
                    f"Tried all {len(ads)} "
                    f"availability domains."
                )
                log(
                    "This workflow run will now exit."
                )
                log(
                    "The next scheduled run can try again."
                )
                log("=" * 60)

                raise SystemExit(0)


        # ----------------------------------------------------
        # INVALID REQUEST / PERMISSION / OTHER ERROR
        # ----------------------------------------------------

        fatal(
            "OCI returned a non-capacity error. "
            "Stopping instead of retrying.\n"
            f"Status: {e.status}\n"
            f"Code: {e.code}\n"
            f"Message: {e.message}"
        )


    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception as e:

        fatal(
            f"Unexpected provisioning error: "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# FALLBACK
# ============================================================

log("")
log("=" * 60)
log("PROVISIONING ATTEMPT FINISHED")
log("=" * 60)

raise SystemExit(0)
