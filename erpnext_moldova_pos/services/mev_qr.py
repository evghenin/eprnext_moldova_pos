"""QR symbol for an MEV verification URL. Byte mode, error correction L, versions 1–5."""

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
	_EXP[_i] = _x
	_LOG[_x] = _i
	_x <<= 1
	if _x & 0x100:
		_x ^= 0x11D
for _i in range(255, 512):
	_EXP[_i] = _EXP[_i - 255]

# version: (size, data codewords, ecc codewords, alignment centers)
_VERSIONS = {
	1: (21, 19, 7, []),
	2: (25, 34, 10, [6, 18]),
	3: (29, 55, 15, [6, 22]),
	4: (33, 80, 20, [6, 26]),
	5: (37, 108, 26, [6, 30]),
}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7}


def qr_svg(text: str) -> str:
	if not text:
		return ""
	modules = _matrix(text.encode("utf-8"))
	size = len(modules)
	rects = []
	for y, row in enumerate(modules):
		for x, on in enumerate(row):
			if on:
				rects.append(f'<rect x="{x}" y="{y}" width="1" height="1"/>')
	body = "".join(rects)
	return (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {size + 8} {size + 8}" '
		f'width="28mm" height="28mm" shape-rendering="crispEdges">{body}</svg>'
	)


def _matrix(data: bytes) -> list[list[bool]]:
	version = _version_for(len(data))
	size, data_len, ecc_len, centers = _VERSIONS[version]
	payload = _data_codewords(data, data_len)
	ecc = _reed_solomon(payload, ecc_len)
	bits = "".join(f"{byte:08b}" for byte in payload + ecc) + ("0" * _REMAINDER[version])
	modules = [[False] * size for _ in range(size)]
	reserved = [[False] * size for _ in range(size)]
	_function_patterns(modules, reserved, centers)
	_place_data(modules, reserved, bits)
	best = None
	best_score = None
	for mask in range(8):
		grid = [row[:] for row in modules]
		_apply_mask(grid, reserved, mask)
		_format(grid, mask)
		score = _penalty(grid)
		if best_score is None or score < best_score:
			best = grid
			best_score = score
	return best


def _version_for(length: int) -> int:
	needed = length + 3
	for version, (_, data_len, _, _) in _VERSIONS.items():
		if data_len >= needed:
			return version
	raise ValueError("MEV verification URL is too long for the receipt QR")


def _data_codewords(data: bytes, length: int) -> list[int]:
	bits = f"{0b0100:04b}{len(data):08b}" + "".join(f"{byte:08b}" for byte in data)
	capacity = length * 8
	bits += "0" * min(4, capacity - len(bits))
	if len(bits) % 8:
		bits += "0" * (8 - len(bits) % 8)
	pad = (0xEC, 0x11)
	pad_index = 0
	while len(bits) < capacity:
		bits += f"{pad[pad_index]:08b}"
		pad_index = 1 - pad_index
	return [int(bits[i : i + 8], 2) for i in range(0, capacity, 8)]


def _reed_solomon(data: list[int], ecc_len: int) -> list[int]:
	generator = [1]
	for i in range(ecc_len):
		generator = _poly_mul(generator, [1, _EXP[i]])
	message = data + [0] * ecc_len
	for i in range(len(data)):
		coef = message[i]
		if coef == 0:
			continue
		log_coef = _LOG[coef]
		for j, term in enumerate(generator):
			message[i + j] ^= _EXP[(_LOG[term] + log_coef) % 255]
	return message[-ecc_len:]


def _poly_mul(left: list[int], right: list[int]) -> list[int]:
	result = [0] * (len(left) + len(right) - 1)
	for i, a in enumerate(left):
		if a == 0:
			continue
		for j, b in enumerate(right):
			if b:
				result[i + j] ^= _EXP[(_LOG[a] + _LOG[b]) % 255]
	return result


def _function_patterns(modules, reserved, centers) -> None:
	size = len(modules)
	for i in range(size):
		_set_function(modules, reserved, 6, i, i % 2 == 0)
		_set_function(modules, reserved, i, 6, i % 2 == 0)
	for x, y in ((3, 3), (size - 4, 3), (3, size - 4)):
		for dy in range(-4, 5):
			for dx in range(-4, 5):
				xx, yy = x + dx, y + dy
				if 0 <= xx < size and 0 <= yy < size:
					_set_function(modules, reserved, xx, yy, max(abs(dx), abs(dy)) not in (2, 4))
	if centers:
		skips = {(centers[0], centers[0]), (centers[0], centers[-1]), (centers[-1], centers[0])}
		for cy in centers:
			for cx in centers:
				if (cx, cy) in skips:
					continue
				for dy in range(-2, 3):
					for dx in range(-2, 3):
						_set_function(modules, reserved, cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
	for index in range(15):
		_reserve_format(reserved, size, index)
	_set_function(modules, reserved, 8, size - 8, True)


def _set_function(modules, reserved, x, y, dark: bool) -> None:
	modules[y][x] = dark
	reserved[y][x] = True


def _reserve_format(reserved, size: int, index: int) -> None:
	if index < 6:
		reserved[index][8] = True
	elif index == 6:
		reserved[7][8] = True
	elif index == 7:
		reserved[8][8] = True
	elif index == 8:
		reserved[8][7] = True
	else:
		reserved[8][14 - index] = True
	if index < 8:
		reserved[8][size - 1 - index] = True
	else:
		reserved[size - 15 + index][8] = True


def _place_data(modules, reserved, bits: str) -> None:
	size = len(modules)
	index = 0
	for right in range(size - 1, 0, -2):
		if right <= 6:
			right -= 1
		upward = (right + 1) & 2 == 0
		for vert in range(size):
			for shift in (0, 1):
				x = right - shift
				y = (size - 1 - vert) if upward else vert
				if reserved[y][x] or index >= len(bits):
					continue
				modules[y][x] = bits[index] == "1"
				index += 1


def _apply_mask(modules, reserved, mask: int) -> None:
	size = len(modules)
	for y in range(size):
		for x in range(size):
			if reserved[y][x]:
				continue
			if _masked(mask, y, x):
				modules[y][x] = not modules[y][x]


def _masked(mask: int, y: int, x: int) -> bool:
	if mask == 0:
		return (y + x) % 2 == 0
	if mask == 1:
		return y % 2 == 0
	if mask == 2:
		return x % 3 == 0
	if mask == 3:
		return (y + x) % 3 == 0
	if mask == 4:
		return (y // 2 + x // 3) % 2 == 0
	if mask == 5:
		return (y * x) % 2 + (y * x) % 3 == 0
	if mask == 6:
		return ((y * x) % 2 + (y * x) % 3) % 2 == 0
	return ((y + x) % 2 + (y * x) % 3) % 2 == 0


def _format(modules, mask: int) -> None:
	data = (0b01 << 3) | mask
	rem = data
	for _ in range(10):
		rem = (rem << 1) ^ ((rem >> 9) * 0x537)
	bits = ((data << 10) | rem) ^ 0x5412
	size = len(modules)

	def paint(x, y, index):
		modules[y][x] = bool(bits >> index & 1)

	for i in range(6):
		paint(8, i, i)
	paint(8, 7, 6)
	paint(8, 8, 7)
	paint(7, 8, 8)
	for i in range(9, 15):
		paint(14 - i, 8, i)
	for i in range(8):
		paint(size - 1 - i, 8, i)
	for i in range(8, 15):
		paint(8, size - 15 + i, i)
	modules[size - 8][8] = True


def _penalty(modules) -> int:
	size = len(modules)
	score = 0
	for row in modules:
		score += _runs(row)
	for x in range(size):
		score += _runs([modules[y][x] for y in range(size)])
	dark = sum(sum(row) for row in modules)
	percent = int(dark * 100 / (size * size))
	score += abs(percent - 50) // 5 * 10
	return score


def _runs(line) -> int:
	score = 0
	run = 1
	for previous, current in zip(line, line[1:]):
		if previous == current:
			run += 1
			if run == 5:
				score += 3
			elif run > 5:
				score += 1
		else:
			run = 1
	return score
