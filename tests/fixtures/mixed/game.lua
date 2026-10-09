local Board = {}

local function clamp(x, lo, hi)
  return math.max(lo, math.min(hi, x))
end

function Board.new(size)
  local self = setmetatable({}, { __index = Board })
  self:reset(clamp(size, 1, 64))
  return self
end

function Board:reset(size)
  self.size = size
end

local onTick = function(board) board:reset(8) end

return Board
