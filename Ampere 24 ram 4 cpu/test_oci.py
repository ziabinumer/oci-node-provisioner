import oci
import os

config = {
    "user": os.getenv("OCI_USER_ID"),
    "key_content": os.getenv("OCI_PRIVATE_KEY"),
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_ID"),
    "region": os.getenv("OCI_REGION")
}

subnet_id = os.getenv("OCI_SUBNET_ID")

print(f"Region: {config['region']}")
print(f"Testing subnet access...")

try:
    network = oci.core.VirtualNetworkClient(config)

    subnet = network.get_subnet(subnet_id).data

    print("SUBNET ACCESS: OK")
    print(f"Name: {subnet.display_name}")
    print(f"State: {subnet.lifecycle_state}")
    print(f"CIDR: {subnet.cidr_block}")

except oci.exceptions.ServiceError as e:
    print("SUBNET ACCESS FAILED")
    print(f"Status: {e.status}")
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    exit(1)
