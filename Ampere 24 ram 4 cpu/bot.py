import os
import oci
from dotenv import load_dotenv

# Load local .env file
load_dotenv()

# ============================================================
# OCI CONFIGURATION
# ============================================================

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION"),
}

# Additional variables
compartment_id = os.getenv("OCI_COMPARTMENT_ID")
image_id = os.getenv("OCI_IMAGE_ID")
subnet_id = os.getenv("OCI_SUBNET_ID")
public_ssh_key = os.getenv("OCI_PUBLIC_SSH_KEY")


# ============================================================
# CHECK VARIABLES
# ============================================================

variables = {
    "OCI_USER_ID": config["user"],
    "OCI_FINGERPRINT": config["fingerprint"],
    "OCI_TENANCY_ID": config["tenancy"],
    "OCI_REGION": config["region"],
    "OCI_COMPARTMENT_ID": compartment_id,
    "OCI_IMAGE_ID": image_id,
    "OCI_SUBNET_ID": subnet_id,
    "OCI_PRIVATE_KEY": config["key_content"],
    "OCI_PUBLIC_SSH_KEY": public_ssh_key,
}

print("=" * 60)
print("OCI LOCAL CONFIGURATION")
print("=" * 60)

all_present = True

for name, value in variables.items():
    if value:
        # Don't expose secrets
        if name in ("OCI_PRIVATE_KEY", "OCI_PUBLIC_SSH_KEY"):
            print(f"{name}: SET")
        else:
            print(f"{name}: {value}")
    else:
        print(f"{name}: MISSING")
        all_present = False

print("=" * 60)


if not all_present:
    print("ERROR: One or more required variables are missing.")
    exit(1)


# ============================================================
# OCI CLIENT
# ============================================================

print("Creating OCI Compute client...")

try:
    compute = oci.core.ComputeClient(config)
    print("OCI CLIENT: OK")

except Exception as e:
    print("OCI CLIENT: FAILED")
    print(f"Error: {e}")
    exit(1)


# ============================================================
# TEST IMAGE ACCESS
# ============================================================

print()
print("Testing image access...")
print(f"Image ID: {image_id}")

try:
    image = compute.get_image(image_id).data

    print()
    print("IMAGE ACCESS: OK")
    print(f"Name:       {image.display_name}")
    print(f"State:      {image.lifecycle_state}")
    print(f"OS:         {image.operating_system}")
    print(f"Version:    {image.operating_system_version}")

except oci.exceptions.ServiceError as e:
    print()
    print("IMAGE ACCESS FAILED")
    print(f"Status:  {e.status}")
    print(f"Code:    {e.code}")
    print(f"Message: {e.message}")
    exit(1)

except Exception as e:
    print()
    print("IMAGE ACCESS FAILED")
    print(f"Error: {e}")
    exit(1)


# ============================================================
# TEST COMPARTMENT ACCESS
# ============================================================

print()
print("Testing compartment access...")

try:
    identity = oci.identity.IdentityClient(config)

    compartment = identity.get_compartment(compartment_id).data

    print("COMPARTMENT ACCESS: OK")
    print(f"Name:  {compartment.name}")
    print(f"State: {compartment.lifecycle_state}")

except oci.exceptions.ServiceError as e:
    print("COMPARTMENT ACCESS FAILED")
    print(f"Status:  {e.status}")
    print(f"Code:    {e.code}")
    print(f"Message: {e.message}")
    exit(1)


# ============================================================
# TEST SUBNET ACCESS
# ============================================================

print()
print("Testing subnet access...")

try:
    virtual_network = oci.core.VirtualNetworkClient(config)

    subnet = virtual_network.get_subnet(subnet_id).data

    print("SUBNET ACCESS: OK")
    print(f"Name:       {subnet.display_name}")
    print(f"State:      {subnet.lifecycle_state}")
    print(f"CIDR:       {subnet.cidr_block}")
    print(f"VCN ID:     {subnet.vcn_id}")

except oci.exceptions.ServiceError as e:
    print("SUBNET ACCESS FAILED")
    print(f"Status:  {e.status}")
    print(f"Code:    {e.code}")
    print(f"Message: {e.message}")
    exit(1)


print()
print("=" * 60)
print("ALL OCI TESTS PASSED")
print("=" * 60)
