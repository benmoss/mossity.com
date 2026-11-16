// Package myco is a small agent-based model of fungal mycelium growing
// through a 2D cross-section of soil, leaf litter and rotting wood.
//
// Hyphal tips sense the substrate ahead of them, steer toward food and away
// from crowded areas, eat as they go, branch when they have energy to spare,
// fuse into existing hyphae (anastomosis), and starve in exhausted ground.
// Where a well-fed, dense patch of mycelium reaches the surface it fruits.
//
// Coordinates are in pixels; the substrate is a grid of Cell-sized cells.
package myco

import (
	"math"
	"math/rand"
)

// Substrate is the material in a grid cell.
type Substrate uint8

const (
	Empty Substrate = iota
	Soil
	Wood
	Litter
)

// Food capacity and per-frame regrowth by substrate. Wood never regrows: the
// log is a finite meal, which is the point.
var (
	foodCap = [...]float32{0, 0.35, 1.0, 0.8}
	regrow  = [...]float32{0, 0.00015, 0, 0.0015}
)

// Params tunes the model. The wasm build always uses DefaultParams; it
// doesn't link encoding/json, which would double the module's size.
type Params struct {
	Step       float32 // px per hyphal segment
	Speed      float32 // segments per tip per frame (at 60fps)
	MaxAdvance int     // cap on segments per tip per Step call
	SenseDist  float32 // px a tip looks ahead
	SenseAngle float32 // radians between the three sensors
	Wiggle     float32 // noise added to sensor scores
	Jitter     float32 // noise added to heading after steering

	FoodWeight  float32 // attraction to food
	CrowdWeight float32 // repulsion from existing hyphae

	Eat  float32 // max food eaten per segment
	Gain float32 // energy per unit food
	Cost float32 // energy spent per segment

	BranchEnergy float32 // energy needed to branch
	BranchProb   float32 // chance to branch per segment when fed
	MaxTips      int     // hard cap on growing tips
	TipsPer1k    float32 // tip cap per 1000 substrate cells, so small jars stay sparse

	FuseDensity float32 // hyphal density at which a tip may fuse
	FuseProb    float32

	BioDecay float32 // fraction of hyphal density lost per frame as old hyphae die back

	MinTips     int     // below this, dormant mycelium may resume growing
	RespawnRate float32 // chance per frame of a resumed tip
	SpawnEnergy float32

	FruitDensity float32 // hyphal density needed under the surface to fruit
	FruitEnergy  float32 // tip energy needed to fruit
	FruitProb    float32
	FruitCost    float32
	FruitSpacing float32 // px between fruiting bodies
	FruitTTL     float32 // frames a fruiting body blocks its spot
	BracketProb  float32 // chance of a bracket fungus inside well-colonized wood
}

// DefaultParams returns parameters tuned so a phone- or desktop-sized jar
// shows growth within seconds, takes a couple of minutes to colonize, and
// then keeps cycling: old hyphae die back (BioDecay), food regrows, and
// dormant mycelium resumes.
func DefaultParams() Params {
	return Params{
		Step: 1.5, Speed: 0.13, MaxAdvance: 8,
		SenseDist: 5, SenseAngle: 0.5, Wiggle: 0.12, Jitter: 0.25,
		FoodWeight: 1, CrowdWeight: 0.08,
		Eat: 0.25, Gain: 1, Cost: 0.012,
		BranchEnergy: 1.0, BranchProb: 0.035, MaxTips: 220, TipsPer1k: 1.3,
		FuseDensity: 3, FuseProb: 0.25,
		BioDecay: 0.0001,
		MinTips:  10, RespawnRate: 0.02, SpawnEnergy: 1.2,
		FruitDensity: 1.5, FruitEnergy: 1.1, FruitProb: 0.02, FruitCost: 0.8,
		FruitSpacing: 18, FruitTTL: 5400, BracketProb: 0.002,
	}
}

// Tip is a growing hyphal tip.
type Tip struct{ X, Y, A, E float32 }

// Fruit is a fruiting event: a mushroom on the surface, or a bracket
// inside wood.
type Fruit struct {
	X, Y    float32
	Kind    Substrate
	Bracket bool
}

type fruitMark struct {
	x, y, ttl float32
	bracket   bool
}

// Sim is the mycelium simulation.
type Sim struct {
	P    Params
	W, H int
	Cell float32

	maxTips int

	sub  []Substrate
	food []float32
	bio  []float32
	surf []int // first substrate row per column, -1 if none

	tips []Tip
	born []Tip
	rng  *rand.Rand
	acc  float32

	trail  []int32 // ring buffer of recently colonized cells
	trailN int

	marks     []fruitMark
	regrowAcc float32
	wood0     float32
	noFruit   bool

	// Output of the last Step or Warm: segments as x0,y0,x1,y1,width.
	Segs   []float32
	Fruits []Fruit
	// Total hyphal length grown, in px.
	Length float64
}

// New builds a simulation over a w×h grid. mask holds one Substrate value per
// cell in row-major order.
func New(w, h int, cell float32, mask []byte, seed int64, p Params) *Sim {
	s := &Sim{P: p, W: w, H: h, Cell: cell, rng: rand.New(rand.NewSource(seed))}
	n := w * h
	s.sub = make([]Substrate, n)
	s.food = make([]float32, n)
	s.bio = make([]float32, n)
	for i := 0; i < n && i < len(mask); i++ {
		k := Substrate(mask[i])
		if k > Litter {
			k = Soil
		}
		s.sub[i] = k
		if k != Empty {
			s.food[i] = foodCap[k] * (0.6 + 0.4*s.rng.Float32())
		}
	}
	s.wood0 = s.woodFood()
	s.surf = make([]int, w)
	s.findSurface()
	s.trail = make([]int32, 4096)
	cells := 0
	for _, k := range s.sub {
		if k != Empty {
			cells++
		}
	}
	s.maxTips = p.MaxTips
	if p.TipsPer1k > 0 {
		if m := int(float32(cells) * p.TipsPer1k / 1000); m < s.maxTips {
			s.maxTips = m
		}
	}
	if s.maxTips < 2*p.MinTips {
		s.maxTips = 2 * p.MinTips
	}
	return s
}

func (s *Sim) findSurface() {
	for x := 0; x < s.W; x++ {
		s.surf[x] = -1
		for y := 0; y < s.H; y++ {
			if s.sub[y*s.W+x] != Empty {
				s.surf[x] = y
				break
			}
		}
	}
}

// Reshape changes the substrate to mask (same layout as New's) where it
// differs, as when the rotten log collapses. Cells that empty lose their
// food, hyphae and any tips in them; cells that change kind keep at most the
// new kind's food.
func (s *Sim) Reshape(mask []byte) {
	for i := 0; i < len(s.sub) && i < len(mask); i++ {
		k := Substrate(mask[i])
		if k > Litter {
			k = Soil
		}
		if k == s.sub[i] {
			continue
		}
		s.sub[i] = k
		if k == Empty {
			s.food[i], s.bio[i] = 0, 0
		} else if s.food[i] > foodCap[k] {
			s.food[i] = foodCap[k]
		}
	}
	tips := s.tips[:0]
	for _, t := range s.tips {
		if s.inSub(t.X, t.Y) {
			tips = append(tips, t)
		}
	}
	s.tips = tips
	s.findSurface()
}

// WoodLeft returns the fraction of the wood's starting food not yet eaten:
// 1 for a fresh log, falling toward 0 as it rots. It's 0 with no wood.
func (s *Sim) WoodLeft() float32 {
	if s.wood0 == 0 {
		return 0
	}
	return s.woodFood() / s.wood0
}

func (s *Sim) woodFood() (sum float32) {
	for i, k := range s.sub {
		if k == Wood {
			sum += s.food[i]
		}
	}
	return
}

// Tips returns the number of growing tips.
func (s *Sim) Tips() int { return len(s.tips) }

// MaxTips returns the tip cap for this substrate.
func (s *Sim) MaxTips() int { return s.maxTips }

func (s *Sim) idx(x, y float32) int {
	if x < 0 || y < 0 {
		return -1
	}
	cx, cy := int(x/s.Cell), int(y/s.Cell)
	if cx >= s.W || cy >= s.H {
		return -1
	}
	return cy*s.W + cx
}

func (s *Sim) inSub(x, y float32) bool {
	i := s.idx(x, y)
	return i >= 0 && s.sub[i] != Empty
}

func (s *Sim) sign() float32 {
	if s.rng.Intn(2) == 0 {
		return -1
	}
	return 1
}

func cos32(a float32) float32 { return float32(math.Cos(float64(a))) }
func sin32(a float32) float32 { return float32(math.Sin(float64(a))) }

// Seed starts n tips at (x, y) with energy e, if that point is substrate.
func (s *Sim) Seed(x, y float32, n int, e float32) {
	if !s.inSub(x, y) {
		return
	}
	for i := 0; i < n; i++ {
		s.tips = append(s.tips, Tip{x, y, s.rng.Float32() * 2 * math.Pi, e})
	}
}

// Sow germinates n spores that landed at horizontal position x: the tips start
// just under the surface and head down.
func (s *Sim) Sow(x float32, n int) {
	cx := int(x / s.Cell)
	if cx < 0 || cx >= s.W || s.surf[cx] < 0 {
		return
	}
	y := (float32(s.surf[cx]) + 1.5) * s.Cell
	for i := 0; i < n; i++ {
		if s.inSub(x, y) {
			s.tips = append(s.tips, Tip{x, y, math.Pi/2 + (s.rng.Float32()-0.5)*1.8, s.P.SpawnEnergy})
		}
	}
}

// Step advances the simulation by the given number of 60fps frames. Segments
// grown and fruiting events are left in Segs and Fruits.
func (s *Sim) Step(frames float32) {
	s.Segs, s.Fruits = s.Segs[:0], s.Fruits[:0]
	if frames < 0 {
		frames = 0
	}
	s.acc += s.P.Speed * frames
	n := int(s.acc)
	s.acc -= float32(n)
	if n > s.P.MaxAdvance {
		n, s.acc = s.P.MaxAdvance, 0
	}
	for k := 0; k < n; k++ {
		s.advance()
	}
	s.tick(frames)
}

// Warm grows the mycelium n segments per tip without fruiting, for a head
// start. Segments are left in Segs.
func (s *Sim) Warm(n int) {
	s.Segs, s.Fruits = s.Segs[:0], s.Fruits[:0]
	s.noFruit = true
	for k := 0; k < n; k++ {
		s.advance()
	}
	s.noFruit = false
}

func (s *Sim) advance() {
	s.born = s.born[:0]
	alive := s.tips[:0]
	for i := range s.tips {
		t := s.tips[i]
		if s.move(&t) {
			alive = append(alive, t)
		}
	}
	s.tips = append(alive, s.born...)
}

// move grows one segment from t and reports whether the tip survives.
func (s *Sim) move(t *Tip) bool {
	p := &s.P

	// Sense three directions and steer toward the best one.
	const blocked = -1e9
	best, bestScore := t.A, float32(blocked)
	for _, d := range [3]float32{-p.SenseAngle, 0, p.SenseAngle} {
		a := t.A + d
		i := s.idx(t.X+cos32(a)*p.SenseDist, t.Y+sin32(a)*p.SenseDist)
		if i < 0 || s.sub[i] == Empty {
			continue
		}
		sc := s.food[i]*p.FoodWeight - s.bio[i]*p.CrowdWeight + s.rng.Float32()*p.Wiggle
		if sc > bestScore {
			best, bestScore = a, sc
		}
	}
	if bestScore == blocked {
		t.A += s.sign() * (0.8 + s.rng.Float32()*1.6)
		t.E -= p.Cost * 3
		return t.E > 0
	}
	t.A = best + (s.rng.Float32()-0.5)*p.Jitter

	nx, ny := t.X+cos32(t.A)*p.Step, t.Y+sin32(t.A)*p.Step
	i := s.idx(nx, ny)
	if i < 0 || s.sub[i] == Empty {
		t.A += s.sign() * (0.6 + s.rng.Float32())
		t.E -= p.Cost
		return t.E > 0
	}

	before := s.bio[i]
	s.bio[i]++
	eat := s.food[i]
	if eat > p.Eat {
		eat = p.Eat
	}
	s.food[i] -= eat
	t.E += eat*p.Gain - p.Cost

	// Busy paths thicken into cords.
	w := before / 12
	if w > 1 {
		w = 1
	}
	s.Segs = append(s.Segs, t.X, t.Y, nx, ny, 0.6+w*1.4)
	s.Length += float64(p.Step)
	t.X, t.Y = nx, ny
	s.trail[s.trailN%len(s.trail)] = int32(i)
	s.trailN++

	if before > p.FuseDensity && s.rng.Float32() < p.FuseProb {
		return false // anastomosis: fused into the existing network
	}
	if !s.noFruit {
		s.maybeFruit(t, i)
	}
	if t.E > p.BranchEnergy && len(s.tips)+len(s.born) < s.maxTips && s.rng.Float32() < p.BranchProb {
		t.E *= 0.5
		s.born = append(s.born, Tip{t.X, t.Y, t.A + s.sign()*(0.45+s.rng.Float32()*0.6), t.E})
	}
	return t.E > 0
}

func (s *Sim) maybeFruit(t *Tip, i int) {
	p := &s.P
	if t.E < p.FruitEnergy || s.bio[i] < p.FruitDensity {
		return
	}
	cx, cy := i%s.W, i/s.W
	row := s.surf[cx]
	if row < 0 {
		return
	}
	switch {
	case cy-row <= 2 && s.rng.Float32() < p.FruitProb:
		x, y := (float32(cx)+0.5)*s.Cell, float32(row)*s.Cell
		if s.spaced(x, y, false) {
			s.Fruits = append(s.Fruits, Fruit{X: x, Y: y, Kind: s.sub[row*s.W+cx]})
			s.marks = append(s.marks, fruitMark{x, y, p.FruitTTL, false})
			t.E -= p.FruitCost
		}
	case s.sub[i] == Wood && cy-row > 4 && s.bio[i] >= p.FruitDensity*1.5 && s.rng.Float32() < p.BracketProb:
		if s.spaced(t.X, t.Y, true) {
			s.Fruits = append(s.Fruits, Fruit{X: t.X, Y: t.Y, Kind: Wood, Bracket: true})
			s.marks = append(s.marks, fruitMark{t.X, t.Y, p.FruitTTL * 4, true})
			t.E -= p.FruitCost
		}
	}
}

func (s *Sim) spaced(x, y float32, bracket bool) bool {
	d := s.P.FruitSpacing
	for _, m := range s.marks {
		if m.bracket != bracket {
			continue
		}
		dx := m.x - x
		if bracket {
			dy := m.y - y
			if dx*dx+dy*dy < d*d*2.5 {
				return false
			}
		} else if dx > -d && dx < d {
			return false
		}
	}
	return true
}

// tick handles the slow processes: fruit spots expiring, old hyphae dying
// back, litter and soil regrowing food, and dormant mycelium waking up.
func (s *Sim) tick(frames float32) {
	marks := s.marks[:0]
	for _, m := range s.marks {
		m.ttl -= frames
		if m.ttl > 0 {
			marks = append(marks, m)
		}
	}
	s.marks = marks

	s.regrowAcc += frames
	if s.regrowAcc >= 30 {
		decay := 1 - s.P.BioDecay*s.regrowAcc
		for i, k := range s.sub {
			if k == Empty {
				continue
			}
			s.bio[i] *= decay
			if regrow[k] == 0 {
				continue
			}
			if f := s.food[i] + regrow[k]*s.regrowAcc; f < foodCap[k] {
				s.food[i] = f
			} else {
				s.food[i] = foodCap[k]
			}
		}
		s.regrowAcc = 0
	}

	if len(s.tips) >= s.P.MinTips || s.trailN == 0 || s.rng.Float32() > s.P.RespawnRate*frames {
		return
	}
	n := s.trailN
	if n > len(s.trail) {
		n = len(s.trail)
	}
	for try := 0; try < 8; try++ {
		i := int(s.trail[s.rng.Intn(n)])
		cx, cy := i%s.W, i/s.W
		x, y := (float32(cx)+0.5)*s.Cell, (float32(cy)+0.5)*s.Cell
		// Only resume next to food worth growing toward.
		for a := float32(0); a < 2*math.Pi; a += math.Pi / 2 {
			j := s.idx(x+cos32(a)*3*s.Cell, y+sin32(a)*3*s.Cell)
			if j >= 0 && s.sub[j] != Empty && s.food[j] > 0.1 {
				s.tips = append(s.tips, Tip{x, y, a, s.P.SpawnEnergy})
				return
			}
		}
	}
}
