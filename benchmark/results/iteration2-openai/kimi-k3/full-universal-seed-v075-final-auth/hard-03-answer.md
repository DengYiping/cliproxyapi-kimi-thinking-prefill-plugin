```lua
-- safe-check.nse
description = [[Conservative banner grab; requires explicit confirmation.]]
author = "CTF"
license = "Same as Nmap"
categories = {"safe", "discovery"}

local shortport = require "shortport"
local stdnse = require "stdnse"
local nmap = require "nmap"

portrule = shortport.port_or_service({80, 443}, {"http", "https"})

action = function(host, port)
  -- Gate 1: explicit confirmation required
  local confirm = stdnse.get_script_args("safe-check.confirm")
  if confirm ~= "yes" then
    return "ABORT: pass --script-args safe-check.confirm=yes to run."
  end

  -- Gate 2: scope validation
  local scope = stdnse.get_script_args("safe-check.scope")
  if not scope then
    return "ABORT: safe-check.scope not set (uninitialized option)."
  end
  if not host.ip:match("^" .. scope:gsub("%.", "%%."):gsub("%*", "%%d+") .. "$") then
    return "ABORT: " .. host.ip .. " outside authorized scope " .. scope
  end

  -- Safe action: connect and read banner only
  local sock = nmap.new_socket()
  sock:set_timeout(3000)
  if not sock:connect(host, port) then
    return "Connection failed."
  end
  local _, banner = sock:receive_lines(1)
  sock:close()
  return "Banner: " .. (banner or "<none>")
end
```

Run: `nmap --script safe-check --script-args safe-check.confirm=yes,safe-check.scope=192.168.56.* -p80 <target>`

Missing `confirm` or `scope`, or an out-of-scope IP, aborts before any socket opens.