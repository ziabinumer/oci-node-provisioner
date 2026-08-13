import oci
import os

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION")
}

image_id = os.getenv("OCI_IMAGE_ID")

print(f"Region: {config['region']}")
print("Testing image access...")

try:
    compute = oci.core.ComputeClient(config)

    image = compute.get_image(image_id).data

    print("IMAGE ACCESS: OK")
    print(f"Name: {image.display_name}")
    print(f"State: {image.lifecycle_state}")
    print(f"OS: {image.operating_system}")
    print(f"Version: {image.operating_system_version}")

except oci.exceptions.ServiceError as e:
    print("IMAGE ACCESS FAILED")
    print(f"Status: {e.status}")
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    exit(1)
