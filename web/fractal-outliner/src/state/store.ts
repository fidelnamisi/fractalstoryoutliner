import { create } from 'zustand';
import { GraphState, BaseNode, K } from '../model/types';

function id(prefix: string) { return `${prefix}_${Math.random().toString(36).slice(2, 8)}`; }

function makeNode(kind: BaseNode['kind'], title: string, body: string, x: number, y: number, w: number, h: number, parentId?: string): BaseNode {
  return {
    id: id(kind), kind, title, body,
    pos: { x, y }, size: { w, h }, headerHeight: K.headerHeight,
    expanded: true, attachedToParent: Boolean(parentId), parentId,
    relativeOffset: parentId ? { x: 0, y: 0 } : undefined,
    childIds: [],
  };
}

// Build initial layout similar to better_toggle_boxes.py
function initialGraph(): GraphState {
  const nodes: Record<string, BaseNode> = {};
  const stepW = 220, beatH = 140;
  const beatsPerStep = 4, stepsPerSeq = 4;
  const stepBodyH = beatsPerStep * beatH + (beatsPerStep - 1) * K.beatGap;
  const stepH = K.headerHeight + K.innerPad + stepBodyH + K.innerPad;
  const seqW = stepsPerSeq * stepW + (stepsPerSeq - 1) * K.outerGap + K.innerPad * 2;
  const seqH = K.headerHeight + K.innerPad + stepH + K.innerPad;
  const actW = 2 * seqW + K.outerGap + K.innerPad * 2;
  const actH = K.headerHeight + K.innerPad + seqH + K.innerPad;

  const act = makeNode('act', 'ACT', 'Body...', 40, 40, actW, actH);
  nodes[act.id] = act;

  const seqs: BaseNode[] = [];
  for (let i = 0; i < 2; i++) {
    const s = makeNode('sequence', `SEQ ${i + 1}`, 'Body...', 0, 0, seqW, seqH, act.id);
    const offsetX = K.innerPad + i * (seqW + K.outerGap);
    const offsetY = K.headerHeight + K.innerPad;
    s.pos = { x: act.pos.x + K.innerPad + offsetX, y: act.pos.y + offsetY };
    s.relativeOffset = { x: offsetX, y: offsetY };
    nodes[s.id] = s; seqs.push(s); act.childIds.push(s.id);
  }

  const steps: BaseNode[] = [];
  for (const s of seqs) {
    for (let i = 0; i < stepsPerSeq; i++) {
      const st = makeNode('step', `STEP ${i + 1}`, 'Body...', 0, 0, stepW, stepH, s.id);
      const offsetX = K.innerPad + i * (stepW + K.outerGap);
      const offsetY = K.headerHeight + K.innerPad;
      st.pos = { x: s.pos.x + offsetX, y: s.pos.y + offsetY };
      st.relativeOffset = { x: offsetX, y: offsetY };
      nodes[st.id] = st; steps.push(st); s.childIds.push(st.id);
    }
  }

  for (const st of steps) {
    const beatW = stepW - K.innerPad * 2;
    for (let j = 0; j < beatsPerStep; j++) {
      const b = makeNode('beat', `BEAT ${j + 1}`, 'Body...', 0, 0, beatW, beatH, st.id);
      const offsetX = K.innerPad;
      const offsetY = K.headerHeight + K.innerPad + j * (beatH + K.beatGap);
      b.pos = { x: st.pos.x + offsetX, y: st.pos.y + offsetY };
      b.relativeOffset = { x: offsetX, y: offsetY };
      nodes[b.id] = b; st.childIds.push(b.id);
    }
  }

  return { nodes, rootId: act.id };
}

export type Action = {
  toggleExpand: (id: string) => void;
  moveNode: (id: string, dx: number, dy: number) => void;
  resizeNode: (id: string, w: number, h: number) => void;
  saveJSON: () => string;
  loadJSON: (json: string) => void;
};

export const useGraph = create<GraphState & Action>((set, get) => ({
  ...initialGraph(),
  toggleExpand: (id) => set((state) => {
    const n = state.nodes[id]; if (!n) return state as any;
    const expanded = !n.expanded; n.expanded = expanded;
    // recursively set visibility via expanded flag only; rendering decides visibility
    return { nodes: { ...state.nodes } } as any;
  }),
  moveNode: (id, dx, dy) => set((state) => {
    const n = state.nodes[id]; if (!n) return state as any;
    n.pos = { x: n.pos.x + dx, y: n.pos.y + dy };
    // Move attached descendants by same delta
    function moveChildren(parent: BaseNode) {
      for (const cid of parent.childIds) {
        const c = state.nodes[cid];
        if (!c) continue;
        if (c.attachedToParent) {
          c.pos = { x: c.pos.x + dx, y: c.pos.y + dy };
          moveChildren(c);
        }
      }
    }
    moveChildren(n);
    return { nodes: { ...state.nodes } } as any;
  }),
  resizeNode: (id, w, h) => set((state) => {
    const n = state.nodes[id]; if (!n) return state as any;
    n.size = { w, h };
    return { nodes: { ...state.nodes } } as any;
  }),
  saveJSON: () => JSON.stringify({ nodes: get().nodes, rootId: get().rootId }, null, 2),
  loadJSON: (json: string) => set(() => {
    const data = JSON.parse(json);
    return { nodes: data.nodes, rootId: data.rootId } as GraphState;
  }),
}));
