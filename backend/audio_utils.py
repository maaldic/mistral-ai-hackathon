import base64


def pcm_bytes_to_base64(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("ascii")


def base64_to_pcm_bytes(b64_str: str) -> bytes:
    return base64.b64decode(b64_str)
