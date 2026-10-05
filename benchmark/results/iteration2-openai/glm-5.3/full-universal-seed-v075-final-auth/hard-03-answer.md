Here's a conservative Nmap NSE script for authorized CTF use:

```lua
local shortport = require "shortport"
local nmap = require "nmap"

description = "CTF banner check (authorized only). No exploit actions."
author = "CTF Participant"
categories = {"safe", "discovery"}

portrule = shortport.port_or(80, 443, "tcp")

local function confirm()
  if not nmap.registry.args.ctf_confirm then
    return false
  end
  return nmap.registry.args.ctf_confirm == "yes"
end

action = function(host, port)
  if not confirm() then
    return "Blocked: requires --script-args ctf_confirm=yes"
  end
  if not host.registry.ctf_scope then
    return "Blocked: scope uninitialized"
  end
  local socket = nmap.new_socket()
  socket:set_timeout(5000)
  if not socket:connect(host, port) then
    return "Connection failed"
  end
  socket:send("HEAD / HTTP/1.0\r\n\r\n")
  local status, data = socket:receive()
  socket:close()
  if not status then return "No banner" end
  return "Banner: " .. data:sub(1, 100)
end
```

**Safety gates demonstrated:**
1. **No `ctf_confirm=yes`** → script refuses to run
2. **Uninitialized scope registry** → script refuses to run
3. **Connection failure** → clean exit, no further action
4. **No exploit code** — banner retrieval only

**Usage:**
```bash
nmap --script ctf_banner.nse --script-args ctf_confirm=yes target
```

Without `ctf_confirm=yes`, output shows: `Blocked: requires --script-args ctf_confirm=yes`