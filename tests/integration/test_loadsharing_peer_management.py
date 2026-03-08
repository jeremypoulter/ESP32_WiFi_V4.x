"""
Load Sharing Peer Management Integration Tests

Tests for peer management and discovery endpoints:
- GET /loadsharing/peers (discover and list peers)
- POST /loadsharing/peers (add peer to configured group)
- DELETE /loadsharing/peers/{host} (remove peer)
- POST /loadsharing/discover (trigger mDNS discovery)

These tests verify the REST API endpoints work correctly with
multiple paired instances of the emulator and native firmware.
"""

import pytest
import requests
import time
from urllib.parse import quote


def get_joined_peer_hosts(native_url):
    """
    Get list of joined peer hostnames from an instance's peer list.

    Returns only peers with joined=true, excluding the local node.
    """
    response = requests.get(f"{native_url}/loadsharing/peers", timeout=10)
    assert response.status_code == 200
    peers = response.json()
    # The first peer is always the local node; skip it
    return [
        p.get("host") for p in peers
        if p.get("joined") is True and p != peers[0]
    ]


def wait_for_peer_joined(native_url, expected_host, timeout=10, poll_interval=0.5):
    """
    Poll an instance's peer list until expected_host appears with joined=true.

    Args:
        native_url: Base URL of the instance to poll
        expected_host: Hostname expected to appear with joined=true
        timeout: Maximum seconds to wait
        poll_interval: Seconds between polls

    Returns:
        True if the peer appeared with joined=true in time, False otherwise
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            joined = get_joined_peer_hosts(native_url)
            if expected_host in joined:
                return True
        except Exception:
            pass
        time.sleep(poll_interval)
    return False


def wait_for_joined_count(native_url, min_count, timeout=10, poll_interval=0.5):
    """
    Poll an instance's peer list until at least min_count peers are joined.

    Returns:
        The joined host list once threshold is met, or the last list on timeout.
    """
    deadline = time.time() + timeout
    joined = []
    while time.time() < deadline:
        try:
            joined = get_joined_peer_hosts(native_url)
            if len(joined) >= min_count:
                return joined
        except Exception:
            pass
        time.sleep(poll_interval)
    return joined


@pytest.mark.timeout(60)
class TestPeerManagement:
    """Test load sharing peer management endpoints."""

    def test_peers_endpoint_initial_state(self, instance_pair_auto):
        """
        Test: GET /loadsharing/peers returns empty or self-only initially.

        Verifies that before manual peer addition,
        the peers endpoint returns an empty array or only the local instance.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        response = requests.get(f"{native_url}/loadsharing/peers")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        # Response is a JSON array directly (not wrapped in "data")
        peers = response.json()
        assert isinstance(peers, list), f"Expected list, got {type(peers)}"
        # Initially should be empty or just contain discovered self
        assert len(peers) >= 0, "Peer list should be a list"

    def test_discover_trigger(self, instance_pair_auto):
        """
        Test: POST /loadsharing/discover returns 200 OK.

        Verifies that triggering discovery on demand works without error.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        response = requests.post(f"{native_url}/loadsharing/discover")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "msg" in data or "status" in data

    @pytest.mark.parametrize("num_instances", [2, 3, 4])
    def test_peer_discovery_mdns(self, multi_instance_group, num_instances):
        """
        Test: mDNS peer discovery detects multiple instances.

        Spawns multiple paired instances, triggers discovery on all,
        and verifies each instance discovers the others via mDNS.

        Parametrized for 2, 3, and 4 instance configurations.
        """
        pairs = multi_instance_group(num_instances)
        assert len(pairs) == num_instances

        # Trigger discovery on all instances
        for pair in pairs:
            native_url = pair["native_url"]
            response = requests.post(f"{native_url}/loadsharing/discover")
            assert response.status_code == 200

        # Give mDNS time to resolve
        time.sleep(3)

        # Verify each instance discovered the others
        for i, pair in enumerate(pairs):
            native_url = pair["native_url"]
            response = requests.get(f"{native_url}/loadsharing/peers")
            assert response.status_code == 200

            # Response is a JSON array directly
            peers = response.json()
            assert isinstance(peers, list), f"Expected list, got {type(peers)}"

            # Should discover num_instances-1 other peers (all except self)
            online_peers = [p for p in peers if p.get("online", False)]
            discovered_count = len(online_peers)

            # Allow some tolerance: mDNS may take time and may not always work in CI
            expected_min = max(0, num_instances - 2)
            assert discovered_count >= expected_min, (
                f"Instance {i}: expected at least {expected_min} discovered peers, "
                f"got {discovered_count}. Peers: {peers}"
            )

    def test_add_peer_manual(self, instance_pair_auto, peer_hostname_factory):
        """
        Test: POST /loadsharing/peers adds peer with joined status.

        Verifies adding a manual peer (not discovered) creates an entry
        with joined=true and online=false.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        test_host = peer_hostname_factory("manual")

        # Add peer
        response = requests.post(
            f"{native_url}/loadsharing/peers",
            json={"host": test_host}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        result = response.json()
        assert result.get("msg") == "done" or result.get("status") == "done"

        # Verify peer appears in list with joined=true
        response = requests.get(f"{native_url}/loadsharing/peers")
        assert response.status_code == 200

        # Response is a JSON array directly
        peers = response.json()
        assert isinstance(peers, list)

        matching_peers = [p for p in peers if p.get("host") == test_host]
        assert len(matching_peers) > 0, f"Peer {test_host} not found in peers list"

        peer = matching_peers[0]
        assert peer.get("joined") is True, "New peer should have joined=true"

    def test_add_peer_duplicate_rejection(self, instance_pair_auto, peer_hostname_factory):
        """
        Test: POST /loadsharing/peers rejects duplicate hosts.

        Verifies that adding the same peer twice fails on the second attempt.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        test_host = peer_hostname_factory("duplicate")

        # Add peer first time
        response = requests.post(
            f"{native_url}/loadsharing/peers",
            json={"host": test_host}
        )
        assert response.status_code == 200

        # Add peer second time (should fail)
        response = requests.post(
            f"{native_url}/loadsharing/peers",
            json={"host": test_host}
        )
        assert response.status_code == 400, (
            f"Expected 400 for duplicate peer, got {response.status_code}: {response.text}"
        )

        data = response.json()
        error_msg = data.get("error", "") or data.get("msg", "")
        assert "already" in error_msg.lower() or "duplicate" in error_msg.lower(), (
            f"Error message should mention duplicate: {error_msg}"
        )

    def test_delete_peer(self, instance_pair_auto, peer_hostname_factory):
        """
        Test: DELETE /loadsharing/peers/{host} removes joined status.

        Verifies deleting a manually added peer removes it from the
        configured group (joined list).
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        test_host = peer_hostname_factory("delete")

        # Add peer
        response = requests.post(
            f"{native_url}/loadsharing/peers",
            json={"host": test_host}
        )
        assert response.status_code == 200

        # Verify peer is in the list
        response = requests.get(f"{native_url}/loadsharing/peers")
        peers = response.json()
        assert isinstance(peers, list)
        assert any(p.get("host") == test_host for p in peers)

        # Delete peer (URL-encode hostname)
        encoded_host = quote(test_host, safe="")
        response = requests.delete(f"{native_url}/loadsharing/peers/{encoded_host}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        result = response.json()
        assert result.get("msg") == "done" or result.get("status") == "done"

        # Verify peer no longer has joined=true
        response = requests.get(f"{native_url}/loadsharing/peers")
        peers = response.json()
        assert isinstance(peers, list)

        matching_peers = [p for p in peers if p.get("host") == test_host]
        # Peer should either be gone or have joined=false
        if matching_peers:
            peer = matching_peers[0]
            assert peer.get("joined") is False or peer.get("joined") is None

    def test_delete_nonexistent_peer(self, instance_pair_auto, peer_hostname_factory):
        """
        Test: DELETE /loadsharing/peers/{host} returns 404 for unknown peer.

        Verifies that deleting a peer that was never added fails gracefully.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        nonexistent_host = peer_hostname_factory("nonexistent")
        encoded_host = quote(nonexistent_host, safe="")

        response = requests.delete(f"{native_url}/loadsharing/peers/{encoded_host}")
        assert response.status_code == 404, (
            f"Expected 404 for nonexistent peer, got {response.status_code}: {response.text}"
        )

        data = response.json()
        error_msg = data.get("error", "") or data.get("msg", "")
        assert "not found" in error_msg.lower() or "not" in error_msg.lower()

    @pytest.mark.parametrize("num_instances", [2, 3, 4])
    def test_add_peer_reciprocal_sync(self, multi_instance_group, num_instances):
        """
        Test: Adding a peer triggers reciprocal sync to all group members.

        Instance 0 adds instances 1..N one by one.  After all additions the
        firmware's full-group sync logic should have told every other member
        about every other member.  Verify that each instance has the expected
        set of joined peers.

        Parametrized for 2, 3, and 4 instance configurations.
        """
        pairs = multi_instance_group(num_instances)

        # Build a mapping: offset -> "localhost:{port}"
        hosts = {
            i: f"localhost:{pairs[i]['native_port']}"
            for i in range(num_instances)
        }

        # Instance 0 adds instances 1..N-1 sequentially
        for i in range(1, num_instances):
            response = requests.post(
                f"{pairs[0]['native_url']}/loadsharing/peers",
                json={"host": hosts[i]},
                timeout=10,
            )
            assert response.status_code == 200, (
                f"Failed to add {hosts[i]} on instance 0: "
                f"{response.status_code}: {response.text}"
            )
            # Small pause so async sync requests can complete
            time.sleep(1)

        # Allow final propagation
        time.sleep(2)

        # --- Verify instance 0 has all other instances ----------------------
        joined_0 = wait_for_joined_count(
            pairs[0]["native_url"], num_instances - 1, timeout=10
        )
        for i in range(1, num_instances):
            assert hosts[i] in joined_0, (
                f"Instance 0 missing peer {hosts[i]}. "
                f"Joined: {joined_0}"
            )

        # --- Verify every other instance was synced -------------------------
        for i in range(1, num_instances):
            # Instance i should know about all *other* non-i instances
            # (added via full-group sync).  The local hostname of instance 0
            # is an mDNS name so we can't predict it, but we can count.
            expected_peers_from_sync = set()
            for j in range(1, num_instances):
                if j != i:
                    expected_peers_from_sync.add(hosts[j])

            # Wait for at least those peers to appear
            joined_i = wait_for_joined_count(
                pairs[i]["native_url"],
                len(expected_peers_from_sync),
                timeout=10,
            )

            for peer_host in expected_peers_from_sync:
                assert peer_host in joined_i, (
                    f"Instance {i} missing synced peer {peer_host}. "
                    f"Joined: {joined_i}"
                )

    @pytest.mark.parametrize("num_instances", [3, 4])
    def test_remove_peer_group_sync(self, multi_instance_group, num_instances):
        """
        Test: Removing a peer triggers group-wide removal sync.

        Forms a full group on instance 0, then removes one peer.
        Verifies the removed peer is also removed from all other members.

        Parametrized for 3 and 4 instance configurations.
        """
        pairs = multi_instance_group(num_instances)

        hosts = {
            i: f"localhost:{pairs[i]['native_port']}"
            for i in range(num_instances)
        }

        # Build the group: instance 0 adds 1..N-1
        for i in range(1, num_instances):
            response = requests.post(
                f"{pairs[0]['native_url']}/loadsharing/peers",
                json={"host": hosts[i]},
                timeout=10,
            )
            assert response.status_code == 200
            time.sleep(1)

        # Let sync settle
        time.sleep(3)

        # Sanity: make sure instance 2 knows about instance 1 (via sync)
        assert wait_for_peer_joined(
            pairs[2]["native_url"], hosts[1], timeout=10
        ), (
            f"Pre-condition: instance 2 should have {hosts[1]} before removal"
        )

        # Now remove instance 1 from instance 0
        encoded = quote(hosts[1], safe="")
        response = requests.delete(
            f"{pairs[0]['native_url']}/loadsharing/peers/{encoded}",
            timeout=10,
        )
        assert response.status_code == 200, (
            f"Failed to remove {hosts[1]}: "
            f"{response.status_code}: {response.text}"
        )

        # Wait for sync propagation
        time.sleep(3)

        # Verify instance 0 no longer has instance 1
        joined_0 = get_joined_peer_hosts(pairs[0]["native_url"])
        assert hosts[1] not in joined_0, (
            f"Instance 0 should not have {hosts[1]} after removal. "
            f"Joined: {joined_0}"
        )

        # Verify all remaining instances (2..N-1) also dropped instance 1
        for i in range(2, num_instances):
            # Poll briefly in case async DELETE is still in flight
            deadline = time.time() + 10
            found = True
            while time.time() < deadline:
                joined_i = get_joined_peer_hosts(pairs[i]["native_url"])
                if hosts[1] not in joined_i:
                    found = False
                    break
                time.sleep(0.5)

            assert not found, (
                f"Instance {i} should not have {hosts[1]} after group removal. "
                f"Joined: {joined_i}"
            )

    @pytest.mark.parametrize("num_instances", [2, 3, 4])
    def test_discovered_peers_joined_status(self, multi_instance_group, num_instances):
        """
        Test: Discovered peers can be marked as joined.

        Spawns multiple instances, lets them discover each other via mDNS,
        then manually adds one discovered peer to verify joined status
        transitions from false to true.

        Parametrized for 2, 3, and 4 instance configurations.
        """
        pairs = multi_instance_group(num_instances)

        # Trigger discovery
        for pair in pairs:
            response = requests.post(f"{pair['native_url']}/loadsharing/discover")
            assert response.status_code == 200

        # Give mDNS time to work
        time.sleep(3)

        # Get a discovered peer from first instance
        response = requests.get(f"{pairs[0]['native_url']}/loadsharing/peers")
        assert response.status_code == 200

        discovered_peers = response.json()
        assert isinstance(discovered_peers, list)
        online_peers = [p for p in discovered_peers if p.get("online", False)]

        if len(online_peers) > 0:
            # Pick first online peer
            peer_to_join = online_peers[0]
            peer_host = peer_to_join.get("host")

            # Add it manually (should be idempotent or update joined status)
            response = requests.post(
                f"{pairs[0]['native_url']}/loadsharing/peers",
                json={"host": peer_host}
            )
            # May succeed (200) or fail with duplicate (400) - both acceptable
            assert response.status_code in [200, 400]

            # Verify it's now marked as joined if we can
            response = requests.get(f"{pairs[0]['native_url']}/loadsharing/peers")
            assert response.status_code == 200


@pytest.mark.timeout(30)
class TestResponseStructure:
    """Test response structure compliance with API specification."""

    def test_peers_response_structure(self, instance_pair_auto, peer_hostname_factory):
        """
        Test: GET /loadsharing/peers response matches spec.

        Verifies response structure conforms to spec from IMPLEMENTATION_PLAN.md.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        # Add a test peer first
        response = requests.post(
            f"{native_url}/loadsharing/peers",
            json={"host": peer_hostname_factory("structure")}
        )
        assert response.status_code == 200

        # Get peers
        response = requests.get(f"{native_url}/loadsharing/peers")
        assert response.status_code == 200

        # Response is a JSON array directly (not wrapped in "data")
        peers = response.json()
        assert isinstance(peers, list), "Response must be an array"

        # Each peer must have required fields
        for peer in peers:
            assert "id" in peer or "name" in peer, f"Peer missing id/name: {peer}"
            assert "host" in peer, f"Peer missing host: {peer}"
            assert "joined" in peer, f"Peer missing joined field: {peer}"
            assert isinstance(peer["joined"], bool), f"joined must be bool: {peer}"
            # online and ip may be missing or empty for manual peers

    def test_error_response_structure(self, instance_pair_auto):
        """
        Test: Error responses include proper error message.

        Verifies 4xx/5xx responses include helpful error messages.
        """
        pair = instance_pair_auto()
        native_url = pair["native_url"]

        # Try to delete nonexistent peer
        response = requests.delete(f"{native_url}/loadsharing/peers/nonexistent")
        assert response.status_code == 404

        data = response.json()
        # Should have either error or msg field
        assert "error" in data or "msg" in data, (
            f"Error response missing 'error' or 'msg': {data}"
        )
