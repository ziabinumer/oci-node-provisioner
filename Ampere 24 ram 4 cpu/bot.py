import oci
import os
import time
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION")
}

required_vars = [
    "OCI_USER_ID",
    "OCI_PRIVATE_KEY",
    "OCI_FINGERPRINT",
    "OCI_TENANCY_ID",
    "OCI_REGION",
    "OCI_SUBNET_ID",
    "OCI_IMAGE_ID",
    "OCI_PUBLIC_SSH_KEY"
]

missing = [v for v in required_vars if not os.getenv(v)]

if missing:
    print("CRITICAL ERROR: Missing environment variables:")
    for var in missing:
        print(f"  - {var}")
    exit(1)


# ============================================================
# INSTANCE SETTINGS
# ============================================================

COMPARTMENT_ID = os.getenv("OCI_TENANCY_ID")
SUBNET_ID = os.getenv("OCI_SUBNET_ID")
IMAGE_ID = os.getenv("OCI_IMAGE_ID")
PUBLIC_SSH_KEY = os.getenv("OCI_PUBLIC_SSH_KEY").strip()

INSTANCE_NAME = "FX-Backend-Server"

SHAPE = "VM.Standard.A1.Flex"
OCPUS = 1
MEMORY_GB = 6
BOOT_VOLUME_GB = 100

TOTAL_ATTEMPTS = 60
RETRY_DELAY = 60


# ============================================================
# OCI CLIENTS
# ============================================================

try:
    compute_client = oci.core.ComputeClient(config)
    identity_client = oci.identity.IdentityClient(config)
    network_client = oci.core.VirtualNetworkClient(config)

    print("OCI authentication successful.")
    print(f"Region: {config['region']}")

except Exception as e:
    print(f"OCI initialization failed: {e}")
    exit(1)


# ============================================================
# SSH KEY CHECK
# ============================================================

if not PUBLIC_SSH_KEY:
    print("CRITICAL ERROR: OCI_PUBLIC_SSH_KEY is empty.")
    exit(1)

print("SSH public key loaded successfully.")


# ============================================================
# GET AVAILABILITY DOMAINS
# ============================================================

try:
    print("Discovering availability domains...")

    ads_response = identity_client.list_availability_domains(
        compartment_id=COMPARTMENT_ID
    )

    ads = [ad.name for ad in ads_response.data]

    if not ads:
        print("CRITICAL ERROR: No availability domains found.")
        exit(1)

    print("Available availability domains:")

    for ad in ads:
        print(f"  - {ad}")

except Exception as e:
    print(f"Failed to retrieve availability domains: {e}")
    exit(1)


# ============================================================
# VERIFY SUBNET
# ============================================================

try:
    subnet = network_client.get_subnet(SUBNET_ID).data

    print()
    print("Subnet:")
    print(f"  Name: {subnet.display_name}")
    print(f"  State: {subnet.lifecycle_state}")
    print(f"  CIDR: {subnet.cidr_block}")

    if subnet.lifecycle_state != "AVAILABLE":
        print("WARNING: Subnet is not AVAILABLE.")

except oci.exceptions.ServiceError as e:
    print("CRITICAL ERROR: Cannot access subnet.")
    print(f"Status: {e.status}")
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    exit(1)


# ============================================================
# VERIFY IMAGE
# ============================================================

try:
    image = compute_client.get_image(IMAGE_ID).data

    print()
    print("Image:")
    print(f"  Name: {image.display_name}")
    print(f"  State: {image.lifecycle_state}")
    print(f"  OS: {image.operating_system}")
    print(f"  Version: {image.operating_system_version}")

    if image.lifecycle_state != "AVAILABLE":
        print("CRITICAL ERROR: Image is not AVAILABLE.")
        exit(1)

except oci.exceptions.ServiceError as e:
    print("CRITICAL ERROR: Cannot access image.")
    print(f"Status: {e.status}")
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    exit(1)


# ============================================================
# CHECK FOR EXISTING INSTANCE
# ============================================================

try:
    print()
    print(f"Checking for existing instance '{INSTANCE_NAME}'...")

    instances = compute_client.list_instances(
        compartment_id=COMPARTMENT_ID
    ).data

    for instance in instances:

        if instance.display_name == INSTANCE_NAME:

            print()
            print("=" * 60)
            print("INSTANCE ALREADY EXISTS")
            print("=" * 60)
            print(f"OCID: {instance.id}")
            print(f"State: {instance.lifecycle_state}")
            print("=" * 60)

            exit(0)

    print("No existing instance found.")

except oci.exceptions.ServiceError as e:

    print("WARNING: Could not check existing instances.")
    print(f"Status: {e.status}")
    print(f"Message: {e.message}")

    print("Continuing with provisioning...")


# ============================================================
# PROVISIONING LOOP
# ============================================================

for attempt in range(1, TOTAL_ATTEMPTS + 1):

    current_ad = ads[(attempt - 1) % len(ads)]

    print()
    print("=" * 60)
    print(f"PROVISIONING ATTEMPT {attempt}/{TOTAL_ATTEMPTS}")
    print("=" * 60)
    print(f"Availability Domain: {current_ad}")
    print(f"Shape: {SHAPE}")
    print(f"OCPUs: {OCPUS}")
    print(f"Memory: {MEMORY_GB} GB")
    print(f"Boot Volume: {BOOT_VOLUME_GB} GB")
    print("=" * 60)

    try:

        launch_details = oci.core.models.LaunchInstanceDetails(

            display_name=INSTANCE_NAME,

            compartment_id=COMPARTMENT_ID,

            availability_domain=current_ad,

            shape=SHAPE,

            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=OCPUS,
                memory_in_gbs=MEMORY_GB
            ),

            source_details=oci.core.models.InstanceSourceViaImageDetails(
                source_type="image",
                image_id=IMAGE_ID,
                boot_volume_size_in_gbs=BOOT_VOLUME_GB
            ),

            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=SUBNET_ID,
                assign_public_ip=True,
                assign_private_dns_record=True,
                display_name="forexalertsvnic"
            ),

            metadata={
                "ssh_authorized_keys": PUBLIC_SSH_KEY
            }
        )

        print("Sending launch request to OCI...")

        response = compute_client.launch_instance(
            launch_details
        )

        instance = response.data

        print()
        print("=" * 60)
        print("INSTANCE CREATION REQUEST ACCEPTED")
        print("=" * 60)
        print(f"Instance OCID: {instance.id}")
        print(f"State: {instance.lifecycle_state}")
        print("=" * 60)

        # ====================================================
        # WAIT FOR RUNNING
        # ====================================================

        print()
        print("Waiting for instance to become RUNNING...")

        try:

            waiter = oci.wait_until(
                compute_client,

                compute_client.get_instance(
                    instance.id
                ),

                evaluate_response=lambda response:
                    response.data.lifecycle_state
                    in ["RUNNING", "TERMINATED"],

                max_wait_seconds=600,

                max_interval_seconds=15
            )

            final_instance = waiter.data

            print(
                f"Final lifecycle state: "
                f"{final_instance.lifecycle_state}"
            )

            if final_instance.lifecycle_state != "RUNNING":

                print(
                    "Instance did not reach RUNNING state."
                )

                exit(1)

        except Exception as e:

            print(
                f"WARNING: Could not confirm RUNNING state: {e}"
            )

            print(
                "The instance may still be starting."
            )


        # ====================================================
        # GET PUBLIC IP
        # ====================================================

        print()
        print("Retrieving network information...")

        try:

            vnic_attachments = compute_client.list_vnic_attachments(
                compartment_id=COMPARTMENT_ID,
                instance_id=instance.id
            ).data

            if not vnic_attachments:

                print("No VNIC attachment found.")
                exit(0)

            vnic_id = vnic_attachments[0].vnic_id

            vnic = network_client.get_vnic(
                vnic_id
            ).data

            print()
            print("=" * 60)
            print("INSTANCE READY")
            print("=" * 60)

            print(f"Instance OCID: {instance.id}")
            print(f"Private IP:    {vnic.private_ip}")
            print(f"Public IP:     {vnic.public_ip}")

            print()
            print("SSH command:")
            print(
                f"ssh -i ~/.ssh/id_ed25519 "
                f"ubuntu@{vnic.public_ip}"
            )

            print("=" * 60)

        except Exception as e:

            print(
                f"WARNING: Could not retrieve public IP: {e}"
            )

        exit(0)


    # ========================================================
    # OCI SERVICE ERROR
    # ========================================================

    except oci.exceptions.ServiceError as e:

        error_text = str(e).lower()

        print()
        print("OCI API ERROR")
        print(f"Status: {e.status}")
        print(f"Code: {e.code}")
        print(f"Message: {e.message}")

        # ----------------------------------------------------
        # Capacity error
        # ----------------------------------------------------

        if (
            "out of host capacity" in error_text
            or "out of capacity" in error_text
        ):

            print()
            print(
                f"No capacity available in {current_ad}."
            )

            if attempt < TOTAL_ATTEMPTS:

                print(
                    f"Waiting {RETRY_DELAY} seconds "
                    "before next attempt..."
                )

                time.sleep(RETRY_DELAY)

                continue

        # ----------------------------------------------------
        # Any other OCI error
        # ----------------------------------------------------

        print()
        print("This is not being treated as a capacity error.")
        print("Stopping to avoid repeated invalid requests.")

        exit(1)


    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception as e:

        print()
        print("UNEXPECTED ERROR")
        print(type(e).__name__)
        print(e)

        exit(1)


# ============================================================
# ALL ATTEMPTS FAILED
# ============================================================

print()
print("=" * 60)
print("PROVISIONING FAILED")
print("=" * 60)
print(
    f"All {TOTAL_ATTEMPTS} attempts were exhausted."
)
print("=" * 60)

exit(1)
