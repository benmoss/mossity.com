package myco

import "testing"

// soilBox is a w×h grid whose bottom half is soil with a litter layer on top
// and a wood block in the middle.
func soilBox(w, h int) []byte {
	m := make([]byte, w*h)
	for y := h / 2; y < h; y++ {
		for x := 0; x < w; x++ {
			k := Soil
			if y == h/2 {
				k = Litter
			}
			if x > w/3 && x < 2*w/3 && y < h/2+8 {
				k = Wood
			}
			m[y*w+x] = byte(k)
		}
	}
	return m
}

func newTestSim(seed int64) *Sim {
	s := New(100, 60, 2, soilBox(100, 60), seed, DefaultParams())
	s.Seed(100, 90, 4, 1.5)
	return s
}

func TestGrowthStaysInSubstrate(t *testing.T) {
	s := newTestSim(1)
	for i := 0; i < 3000; i++ {
		s.Step(1)
		for j := 0; j+4 < len(s.Segs); j += 5 {
			if x, y := s.Segs[j+2], s.Segs[j+3]; !s.inSub(x, y) {
				t.Fatalf("step %d: segment ends outside substrate at (%.1f, %.1f)", i, x, y)
			}
		}
		if s.Tips() > s.MaxTips() {
			t.Fatalf("step %d: %d tips exceeds MaxTips %d", i, s.Tips(), s.MaxTips())
		}
	}
	if s.Length == 0 {
		t.Fatal("nothing grew")
	}
}

func TestDeterministic(t *testing.T) {
	a, b := newTestSim(42), newTestSim(42)
	for i := 0; i < 1000; i++ {
		a.Step(1)
		b.Step(1)
	}
	if a.Length != b.Length || a.Tips() != b.Tips() {
		t.Fatalf("same seed diverged: %v/%d vs %v/%d", a.Length, a.Tips(), b.Length, b.Tips())
	}
}

func TestWoodGetsEaten(t *testing.T) {
	s := newTestSim(7)
	if got := s.WoodLeft(); got != 1 {
		t.Fatalf("fresh log WoodLeft = %v, want 1", got)
	}
	for i := 0; i < 60*60*5; i++ {
		s.Step(1)
	}
	if got := s.WoodLeft(); got > 0.5 {
		t.Fatalf("wood barely decayed: %.2f left", got)
	}
}

func TestReshapeEmptiesCells(t *testing.T) {
	s := newTestSim(3)
	for i := 0; i < 600; i++ {
		s.Step(1)
	}
	// the wood block crumbles away to nothing
	m := soilBox(100, 60)
	for i, k := range m {
		if Substrate(k) == Wood {
			m[i] = byte(Empty)
		}
	}
	s.Reshape(m)
	if got := s.WoodLeft(); got != 0 {
		t.Fatalf("WoodLeft after the wood went = %v, want 0", got)
	}
	for _, tip := range s.tips {
		if !s.inSub(tip.X, tip.Y) {
			t.Fatalf("tip left outside substrate at (%.1f, %.1f)", tip.X, tip.Y)
		}
	}
	for i := 0; i < 600; i++ {
		s.Step(1)
		for j := 0; j+4 < len(s.Segs); j += 5 {
			if x, y := s.Segs[j+2], s.Segs[j+3]; !s.inSub(x, y) {
				t.Fatalf("segment grew into the old wood at (%.1f, %.1f)", x, y)
			}
		}
	}
}

func TestSowStartsUnderSurface(t *testing.T) {
	s := New(100, 60, 2, soilBox(100, 60), 3, DefaultParams())
	s.Sow(20, 3)
	if s.Tips() != 3 {
		t.Fatalf("want 3 tips, got %d", s.Tips())
	}
	for _, tip := range s.tips {
		if tip.Y < 60 || !s.inSub(tip.X, tip.Y) {
			t.Fatalf("tip at (%.1f, %.1f) is not under the surface", tip.X, tip.Y)
		}
	}
	s.Sow(-5, 3) // off the grid
	if s.Tips() != 3 {
		t.Fatal("sowing off the grid should do nothing")
	}
}

func TestFruits(t *testing.T) {
	s := newTestSim(5)
	fruits := 0
	for i := 0; i < 60*60*3; i++ {
		s.Step(1)
		for _, f := range s.Fruits {
			fruits++
			if !f.Bracket && f.Y != 60 {
				t.Fatalf("surface fruit at y=%.1f, want 60", f.Y)
			}
		}
	}
	if fruits == 0 {
		t.Fatal("expected some fruiting in three simulated minutes")
	}
}

func TestStaysActive(t *testing.T) {
	s := newTestSim(9)
	for i := 0; i < 60*60*4; i++ {
		s.Step(1)
	}
	before := s.Length
	for i := 0; i < 60*60; i++ {
		s.Step(1)
	}
	// Old hyphae die back and food regrows, so the colony should still be
	// exploring after the initial flush instead of sitting dormant.
	if grown := s.Length - before; grown < 1000 {
		t.Fatalf("only %.0f px grown in minute five; mycelium went dormant", grown)
	}
}

func TestTipCapScalesWithArea(t *testing.T) {
	small := New(100, 60, 2, soilBox(100, 60), 1, DefaultParams())
	big := New(400, 240, 2, soilBox(400, 240), 1, DefaultParams())
	if small.MaxTips() >= big.MaxTips() {
		t.Fatalf("small jar cap %d should be below big jar cap %d", small.MaxTips(), big.MaxTips())
	}
	if big.MaxTips() > big.P.MaxTips {
		t.Fatalf("cap %d exceeds hard limit %d", big.MaxTips(), big.P.MaxTips)
	}
}
