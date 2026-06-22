"""
db/repository.py
Centralized data-access / business-logic functions for hosts, groups,
identities, snippets, and port-forward rules. Keeping this logic out of the
UI layer means dialogs stay thin, and the same operations (duplicate host,
resolve chain, etc.) are reused consistently and are independently testable.
"""

from db.models import Host, Identity, Group, PortForward, Snippet


def duplicate_host(db_session, host_id: int, new_label: str = None) -> Host:
    """
    Create a copy of a host (and its identity, if any) so the user can
    tweak one field (e.g. hostname/environment) without rebuilding the
    whole entry. Port-forward rules are copied too; the duplicate is left
    in the same group as the original.
    """
    original = db_session.query(Host).get(host_id)
    if not original:
        raise ValueError("Host not found")

    new_identity = None
    if original.identity:
        src = original.identity
        new_identity = Identity(
            label=f"{src.label} (copy)",
            username=src.username,
            auth_type=src.auth_type,
            enc_password=src.enc_password,
            enc_private_key=src.enc_private_key,
            enc_passphrase=src.enc_passphrase,
            private_key_path=src.private_key_path,
        )
        db_session.add(new_identity)

    new_host = Host(
        label=new_label or f"{original.label} (copy)",
        hostname=original.hostname,
        port=original.port,
        username=original.username,
        identity=new_identity,
        group_id=original.group_id,
        proxy_host_id=original.proxy_host_id,
        terminal_type=original.terminal_type,
        startup_snippet_id=original.startup_snippet_id,
        color_tag=original.color_tag,
        keepalive_interval=original.keepalive_interval,
        host_key_fingerprint=original.host_key_fingerprint,
    )
    db_session.add(new_host)
    db_session.flush()  # need new_host.id for port forwards

    for pf in original.port_forwards:
        db_session.add(PortForward(
            host_id=new_host.id,
            type=pf.type,
            label=pf.label,
            bind_address=pf.bind_address,
            bind_port=pf.bind_port,
            dest_address=pf.dest_address,
            dest_port=pf.dest_port,
            auto_start=pf.auto_start,
        ))

    db_session.commit()
    return new_host


def get_chain_hosts(db_session, host_id: int):
    """
    Return the ordered list of Host objects in a jump-host chain,
    from the entry hop to the target host (inclusive). Useful for
    showing "A -> B -> C" in the UI and for port-forwarding through
    intermediate hops.
    """
    chain = []
    visited = set()
    current = db_session.query(Host).get(host_id)
    while current is not None:
        if current.id in visited:
            raise ValueError("Cycle detected in proxy host chain")
        visited.add(current.id)
        chain.append(current)
        current = current.proxy_host
    chain.reverse()
    return chain


def all_hosts_flat(db_session):
    """Return all hosts ordered by label, for pickers/dropdowns."""
    return db_session.query(Host).order_by(Host.label).all()
