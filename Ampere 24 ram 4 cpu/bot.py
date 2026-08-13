import oci
import os
import time
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# OCI CONFIGURATION
# ============================================================

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION")
}

# Validate required configuration
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

missing = [var for var in required_vars if not os.getenv(var)]

if missing:
    print("CRITICAL ERROR: Missing environment variables:")
    for var in missing:
        print(f"  - {var}")
    exit(1)


# ============================================================
# OCI CLIENTS
# ============================================================

try:
    compute_client = oci.core.ComputeClient(config)
    identity_client = oci.identity.IdentityClient(config)

    print("OCI Authentication Successful.")
    print(f"Region: {config['region']}")

except Exception as e:
    print(f"Authentication Failed: {e}")
    exit(1)


# ============================================================
# INSTANCE CONFIGURATION
# ============================================================

compartment_id = os.getenv("OCI_TENANCY_ID")
subnet_id = os.getenv("OCI_SUBNET_ID")
image_id = os.getenv("OCI_IMAGE_ID")
public_ssh_key = os.getenv("OCI_PUBLIC_SSH_KEY").strip()

INSTANCE_NAME = "FX-Backend-Server"

# Ampere A1 configuration
OCPUS = 1
MEMORY_GB = 6
BOOT_VOLUME_GB = 100

# Number of attempts
TOTAL_ATTEMPTS = 60

# Seconds between capacity attempts
RETRY_DELAY = 60


# ============================================================
# SSH KEY VALIDATION
# ============================================================

if not public_ssh_key:
    print("CRITICAL ERROR: OCI_PUBLIC_SSH_KEY is empty.")
    exit(1)

if not (
    public_ssh_key.startswith("ssh-ed25519 ")
    or public_ssh_key.startswith("ssh-rsa ")
    or public_ssh_key.startswith("ecdsa-")
):
    print("WARNING: OCI_PUBLIC_SSH_KEY does not look like a standard SSH public key.")

print("SSH public key loaded successfully.")


# ============================================================
# DISCOVER AVAILABILITY DOMAINS
# ============================================================

try:
    print("Discovering availability domains...")

    ads_response = identity_client.list_availability_domains(
        tenancy_id=compartment_id
    )

    ads = [ad.name for ad in ads_response.data]

    if not ads:
        print("CRITICAL ERROR: No availability domains found.")
        exit(1)

    print(f"Available availability domains: {ads}")

except Exception as e:
    print(f"CRITICAL ERROR: Failed to retrieve availability domains: {e}")
    exit(1)


# ============================================================
# CHECK FOR EXISTING INSTANCE
# ============================================================

try:
    print(f"Checking whether '{INSTANCE_NAME}' already exists...")

    existing_instances = compute_client.list_instances(
        compartment_id=compartment_id
    ).data

    for instance in existing_instances:
        if instance.display_name == INSTANCE_NAME:
            print(
                f"Instance '{INSTANCE_NAME}' already exists."
            )
            print(f"Instance OCID: {instance.id}")
            print(f"Instance state: {instance.lifecycle_state}")
            print("No new instance will be created.")
            exit(0)

    print("No existing instance found. Proceeding with provisioning.")

except Exception as e:
    print(f"WARNING: Could not check for existing instances: {e}")
    print("Continuing with provisioning attempt...")


# ============================================================
# PROVISIONING LOOP
# ============================================================

for i in range(1, TOTAL_ATTEMPTS + 1):

    current_ad = ads[(i - 1) % len(ads)]

    print()
    print("=" * 60)
    print(f"Attempt {i}/{TOTAL_ATTEMPTS}")
    print(f"Availability Domain: {current_ad}")
    print(f"Shape: VM.Standard.A1.Flex")
    print(f"OCPUs: {OCPUS}")
    print(f"Memory: {MEMORY_GB} GB")
    print("=" * 60)

    try:

        request = oci.core.models.LaunchInstanceDetails(
            display_name=INSTANCE_NAME,

            compartment_id=compartment_id,

            availability_domain=current_ad,

            shape="VM.Standard.A1.Flex",

            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=OCPUS,
                memory_in_gbs=MEMORY_GB
            ),

            source_details=oci.core.models.InstanceSourceViaImageDetails(
                source_type="image",
                image_id=image_id,
                boot_volume_size_in_gbs=BOOT_VOLUME_GB
            ),

            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=True,
                assign_private_dns_record=True,
                display_name="forexalertsvnic"
            ),

            metadata={
                "ssh_authorized_keys": public_ssh_key
            }
        )

        print("Sending launch request to OCI...")

        response = compute_client.launch_instance(request)

        if response.status in (200, 201, 202):

            instance = response.data

            print()
            print("=" * 60)
            print("SUCCESS!")
            print("=" * 60)
            print(f"Instance OCID: {instance.id}")
            print(f"Instance name: {instance.display_name}")
            print(f"Lifecycle state: {instance.lifecycle_state}")
            print("OCI accepted the instance creation request.")
            print("=" * 60)

            # ------------------------------------------------
            # Wait for the instance to become RUNNING
            # ------------------------------------------------

            print()
            print("Waiting for instance to become RUNNING...")

            try:
                waiter_response = oci.wait_until(
                    compute_client,
                    compute_client.get_instance(instance.id),
                    evaluate_response=lambda response: response.data.lifecycle_state
                    in ["RUNNING", "TERMINATED"],
                    max_wait_seconds=600,
                    max_interval_seconds=15
                )

                final_instance = waiter_response.data

                print(
                    f"Final lifecycle state: "
                    f"{final_instance.lifecycle_state}"
                )

                if final_instance.lifecycle_state != "RUNNING":
                    print("Instance did not reach RUNNING state.")
                    exit(1)

            except Exception as e:
                print(f"WARNING: Could not confirm RUNNING state: {e}")
                print("The instance may still be starting.")

            # ------------------------------------------------
            # Retrieve VNIC / Public IP
            # ------------------------------------------------

            try:
                vnic_attachments = compute_client.list_vnic_attachments(
                    compartment_id=compartment_id,
                    instance_id=instance.id
                ).data

                if vnic_attachments:

                    vnic_id = vnic_attachments[0].vnic_id

                    virtual_network_client = oci.core.VirtualNetworkClient(
                        config
                    )

                    vnic = virtual_network_client.get_vnic(
                        vnic_id
                    ).data

                    print()
                    print("=" * 60)
                    print("SERVER INFORMATION")
                    print("=" * 60)
                    print(f"Private IP: {vnic.private_ip}")
                    print(f"Public IP:  {vnic.public_ip}")
                    print()
                    print(
                        f"SSH command:"
                    )
                    print(
                        f"ssh -i ~/.ssh/id_ed25519 ubuntu@{vnic.public_ip}"
                    )
                    print("=" * 60)

            except Exception as e:
                print(f"WARNING: Could not retrieve public IP: {e}")

            exit(0)

    except oci.exceptions.ServiceError as e:

        error_text = str(e).lower()

        # ----------------------------------------------------
        # Capacity errors
        # ----------------------------------------------------

        if (
            "out of host capacity" in error_text
            or "out of capacity" in error_text
        ):
            print(
                "-> Out of host capacity in this availability domain."
            )

            if i < TOTAL_ATTEMPTS:
                print(
                    f"-> Retrying in {RETRY_DELAY} seconds..."
                )
                time.sleep(RETRY_DELAY)

        # ----------------------------------------------------
        # Other OCI errors
        # ----------------------------------------------------

        else:
            print()
            print("OCI API ERROR")
            print(f"Status: {e.status}")
            print(f"Code: {e.code}")
            print(f"Message: {e.message}")

            # Don't blindly retry arbitrary API errors.
            exit(1)

    except Exception as e:

        print()
        print(f"Unexpected error: {e}")
        exit(1)


# ============================================================
# ALL ATTEMPTS EXHAUSTED
# ============================================================

print()
print("=" * 60)
print("PROVISIONING FAILED")
print("=" * 60)
print(
    f"All {TOTAL_ATTEMPTS} attempts were exhausted "
    "without successfully creating the instance."
)
print("=" * 60)

exit(1)
