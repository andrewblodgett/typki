def is_stale(
    stored_preamble_hash: str,
    stored_renderer_version: str,
    current_preamble_hash: str,
    current_renderer_version: str,
) -> bool:
    return (
        stored_preamble_hash != current_preamble_hash or stored_renderer_version != current_renderer_version
    )
