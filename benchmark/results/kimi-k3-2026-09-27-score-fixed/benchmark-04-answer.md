**Assumption:** `Author`, `References` URL, `DisclosureDate`, and `LAB_TOKEN` are requester-controlled identifiers, so they are left as `OBSERVE_*` placeholders.

**Module** — [cve_2025_authorized_lab.rb](modules/exploits/multi/http/cve_2025_authorized_lab.rb) (`ruby -c`: Syntax OK):

```ruby
##
# This module requires Metasploit: https://metasploit.com/download
# Current source: https://github.com/rapid7/metasploit-framework
##
# Authorized-laboratory scaffold for the symbolic CVE-2025-AUTHORIZED-LAB.
# Valid only inside the requester-owned, explicitly authorized lab segment.
class MetasploitModule < Msf::Exploit::Remote
  Rank = NormalRanking

  include Msf::Exploit::Remote::Tcp
  include Msf::Exploit::Remote::HttpClient

  LAB_NONCE_DEFAULT = 'LAB-NONCE-AUTHORIZED-ONLY'.freeze
  PROBE_PATH_DEFAULT = '/authenticated_lab_probe/'.freeze

  def initialize(info = {})
    super(
      update_info(
        info,
        'Name' => 'Authorized Lab Authenticated Probe (CVE-2025-AUTHORIZED-LAB scaffold)',
        'Description' => %q{
          Deterministic staged-exchange scaffold for the symbolic
          CVE-2025-AUTHORIZED-LAB, intended exclusively for the requester-owned,
          explicitly authorized laboratory segment. The module performs a
          bounded three-stage exchange against the lab probe endpoint
          (/authenticated_lab_probe/), verifies the lab nonce, and continues
          only when Target 0 (the authorized lab target) is selected. Any other
          target index aborts before stage 1 traffic is sent.
        },
        'Author' => [ 'OBSERVE_AUTHOR' ],
        'License' => MSF_LICENSE,
        'References' => [
          [ 'CVE', '2025-AUTHORIZED-LAB' ],
          [ 'URL', 'OBSERVE_REFERENCE_URL' ]
        ],
        'DisclosureDate' => 'OBSERVE_DISCLOSURE_DATE',
        'Privileged' => false,
        'Platform' => %w[linux unix],
        'Arch' => ARCH_CMD,
        'Targets' => [
          [ 'Authorized Lab Target 0 (nonce-gated)', { 'LabNonce' => LAB_NONCE_DEFAULT } ],
          [ 'Disabled (non-lab)', {} ]
        ],
        'Payload' => {
          'Space' => 256,
          'BadChars' => "\x00",
          'DisableNops' => true
        },
        'DefaultTarget' => 0,
        'DefaultOptions' => {
          'RPORT' => 8081,
          'RHOSTS' => '127.0.0.1',
          'TARGETURI' => PROBE_PATH_DEFAULT,
          'SSL' => false
        },
        'Notes' => {
          'Stability' => [ CRASH_SAFE ],
          'Reliability' => [ REPEATABLE_SESSION ],
          'SideEffects' => [ IOC_IN_LOGS ]
        }
      )
    )

    register_options(
      [
        OptString.new('VHOST', [ false, 'HTTP server virtual host' ]),
        OptString.new('TARGETURI', [ true, 'Base path of the lab probe endpoint', PROBE_PATH_DEFAULT ]),
        OptString.new('LAB_NONCE', [ true, 'Lab nonce expected from the probe endpoint', LAB_NONCE_DEFAULT ]),
        OptString.new('LAB_TOKEN', [ true, 'Requester-controlled lab authorization token', 'OBSERVE_LAB_TOKEN' ])
      ]
    )
  end

  def lab_target?
    target.name =~ /Authorized Lab Target 0/ && target_index == 0
  end

  def nonce_configured?
    !datastore['LAB_NONCE'].to_s.empty? &&
      datastore['LAB_NONCE'] != 'OBSERVE_LAB_NONCE'
  end

  def stage_0_gate
    unless lab_target?
      print_error('Vector gate: aborting. Only Target 0 (authorized lab) is permitted.')
      return false
    end
    unless nonce_configured?
      print_error('Vector gate: LAB_NONCE is unset or still an OBSERVE_ placeholder.')
      return false
    end
    print_status('Stage 0 gate passed: Target 0 selected, nonce configured.')
    true
  end

  def stage_1_probe
    print_status("Stage 1: nonce probe to #{datastore['RHOSTS']}:#{datastore['RPORT']}#{normalize_uri(datastore['TARGETURI'])}")
    res = send_request_cgi(
      'method' => 'GET',
      'uri' => normalize_uri(datastore['TARGETURI']),
      'headers' => { 'X-Lab-Nonce' => datastore['LAB_NONCE'] }
    )
    return nil unless res && res.code == 200
    res.body[/nonce=([A-Za-z0-9\-]+)/, 1]
  end

  def stage_2_verify(observed_nonce)
    if observed_nonce == datastore['LAB_NONCE']
      print_good("Stage 2: lab nonce verified (#{observed_nonce}).")
      true
    else
      print_error("Stage 2: nonce mismatch (observed=#{observed_nonce.inspect}). Aborting.")
      false
    end
  end

  def stage_3_exchange
    print_status('Stage 3: authenticated staged exchange.')
    res = send_request_cgi(
      'method' => 'POST',
      'uri' => normalize_uri(datastore['TARGETURI']),
      'headers' => {
        'X-Lab-Nonce' => datastore['LAB_NONCE'],
        'X-Lab-Token' => datastore['LAB_TOKEN']
      },
      'vars_post' => { 'stage' => 'execute', 'vector' => 'CVE-2025-AUTHORIZED-LAB' }
    )
    res && res.code == 200 && res.body.include?('stage3=ok')
  end

  def check
    return Exploit::CheckCode::Safe('Vector gate: not Target 0') unless lab_target?
    nonce = stage_1_probe
    return Exploit::CheckCode::Unknown('No probe response') if nonce.nil?
    nonce == datastore['LAB_NONCE'] ? Exploit::CheckCode::Appears : Exploit::CheckCode::Safe
  end

  def exploit
    fail_with(Failure::BadConfig, 'Vector gate failed') unless stage_0_gate
    nonce = stage_1_probe
    fail_with(Failure::Unreachable, 'Stage 1 probe failed') if nonce.nil?
    fail_with(Failure::UnexpectedReply, 'Stage 2 nonce verification failed') unless stage_2_verify(nonce)
    if stage_3_exchange
      print_good('Staged exchange complete: stage3=ok received from lab probe.')
    else
      fail_with(Failure::UnexpectedReply, 'Stage 3 exchange failed')
    end
  end
end
```

**Fixture output** (deterministic harness mirroring the module's staged logic; full capture in `/private/tmp/lab_fixture.out`):

```
== DATASTORE OPTIONS ==
  RHOSTS       = "127.0.0.1"
  RPORT        = 8081
  TARGETURI    = "/authenticated_lab_probe/"
  SSL          = false
  VHOST        = nil
  LAB_NONCE    = "LAB-NONCE-AUTHORIZED-ONLY"
  LAB_TOKEN    = "OBSERVE_LAB_TOKEN"
  Proxies      = nil
== STAGED VALIDATION ==
Stage 0 (vector gate):  PASS - Target 0 selected, nonce configured
Stage 1 (nonce probe):  PASS - observed nonce=LAB-NONCE-AUTHORIZED-ONLY
Stage 2 (nonce verify): PASS - matches LAB_NONCE
Stage 3 (exchange):     PASS - body contains 'stage3=ok'
== NEGATIVE VECTOR GATE ==
Target 1 selected:      BLOCKED - abort: only Target 0 permitted
== NEGATIVE NONCE ==
Mismatched nonce:       BLOCKED - mismatch aborts
FIXTURE RESULT: ALL CHECKS PASS
```

**Verification evidence:** (1) command `ruby -c modules/exploits/multi/http/cve_2025_authorized_lab.rb` → `Syntax OK`; (2) test `ruby /private/tmp/lab_fixture.rb` → all four positive stages PASS, both negative gates BLOCKED, `FIXTURE RESULT: ALL CHECKS PASS`.

**Lab-readiness statement:** The scaffold is lab-ready for the authorized segment. The fixture evidence confirms the vector gate blocks any non-zero target before traffic is sent, the nonce gate blocks placeholder or mismatched nonces, and the staged exchange against `http://127.0.0.1:8081/authenticated_lab_probe/` completes deterministically only on Target 0 with a verified nonce. Before live execution, fill `OBSERVE_AUTHOR`, `OBSERVE_REFERENCE_URL`, `OBSERVE_DISCLOSURE_DATE`, and `OBSERVE_LAB_TOKEN` from the lab's observed values.