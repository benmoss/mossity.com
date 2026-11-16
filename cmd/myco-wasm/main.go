//go:build js && wasm

// Command myco-wasm exposes the mycelium simulation to the browser as a
// global `myco` object:
//
//	myco.init(w, h, cell, maskUint8Array, seed)
//	myco.seed(x, y, n)
//	myco.warm(steps, dstUint8Array) -> number of segments
//	myco.step(frames, dstUint8Array) -> {n, fruits: [x, y, kind, bracket, ...]}
//	myco.sow(x, n)
//	myco.stats() -> {length, tips, wood}
//	myco.reshape(maskUint8Array)
//
// Segments are written to dst (a byte view of a Float32Array) as
// x0, y0, x1, y1, width.
package main

import (
	"syscall/js"
	"unsafe"

	"github.com/benmoss/mossity.com/myco"
)

var sim *myco.Sim

func main() {
	api := js.Global().Get("Object").New()
	api.Set("init", js.FuncOf(initSim))
	api.Set("seed", js.FuncOf(seed))
	api.Set("warm", js.FuncOf(warm))
	api.Set("step", js.FuncOf(step))
	api.Set("sow", js.FuncOf(sow))
	api.Set("stats", js.FuncOf(stats))
	api.Set("reshape", js.FuncOf(reshape))
	js.Global().Set("myco", api)
	js.Global().Call("dispatchEvent", js.Global().Get("Event").New("myco-ready"))
	select {}
}

func initSim(_ js.Value, a []js.Value) any {
	mask := make([]byte, a[3].Get("length").Int())
	js.CopyBytesToGo(mask, a[3])
	sim = myco.New(a[0].Int(), a[1].Int(), float32(a[2].Float()), mask, int64(a[4].Float()), myco.DefaultParams())
	return nil
}

func seed(_ js.Value, a []js.Value) any {
	if sim != nil {
		sim.Seed(float32(a[0].Float()), float32(a[1].Float()), a[2].Int(), sim.P.SpawnEnergy+0.3)
	}
	return nil
}

func sow(_ js.Value, a []js.Value) any {
	if sim != nil {
		sim.Sow(float32(a[0].Float()), a[1].Int())
	}
	return nil
}

func warm(_ js.Value, a []js.Value) any {
	if sim == nil {
		return 0
	}
	sim.Warm(a[0].Int())
	return copySegs(a[1])
}

func step(_ js.Value, a []js.Value) any {
	if sim == nil {
		return nil
	}
	sim.Step(float32(a[0].Float()))
	fruits := make([]any, 0, len(sim.Fruits)*4)
	for _, f := range sim.Fruits {
		b := 0
		if f.Bracket {
			b = 1
		}
		fruits = append(fruits, float64(f.X), float64(f.Y), int(f.Kind), b)
	}
	return map[string]any{"n": copySegs(a[1]), "fruits": fruits}
}

func reshape(_ js.Value, a []js.Value) any {
	if sim != nil {
		mask := make([]byte, a[0].Get("length").Int())
		js.CopyBytesToGo(mask, a[0])
		sim.Reshape(mask)
	}
	return nil
}

func stats(js.Value, []js.Value) any {
	if sim == nil {
		return nil
	}
	return map[string]any{"length": sim.Length, "tips": sim.Tips(), "wood": sim.WoodLeft()}
}

// copySegs copies as many whole segments as fit into dst and returns the count.
func copySegs(dst js.Value) int {
	segs := sim.Segs
	if max := dst.Get("length").Int() / 20 * 5; len(segs) > max {
		segs = segs[:max]
	}
	if len(segs) == 0 {
		return 0
	}
	js.CopyBytesToJS(dst, unsafe.Slice((*byte)(unsafe.Pointer(&segs[0])), len(segs)*4))
	return len(segs) / 5
}
