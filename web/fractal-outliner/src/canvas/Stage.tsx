import React, { useRef, useState } from 'react';
import { Stage, Layer, Group, Rect, Text } from 'react-konva';
import Konva from 'konva';
import { useGraph } from '../state/store';
import { BaseNode, K } from '../model/types';

function zIndexFor(kind: BaseNode['kind']) {
  switch (kind) {
    case 'act': return 0;
    case 'sequence': return 1;
    case 'step': return 2;
    case 'beat': return 4;
  }
}

function Header({ n, onToggle, onDragStart, onDragMove, onDragEnd }: {
  n: BaseNode;
  onToggle: () => void;
  onDragStart: (pt: { x: number; y: number }) => void;
  onDragMove: (pt: { x: number; y: number }) => void;
  onDragEnd: (wasDrag: boolean) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const downRef = useRef<{ x: number; y: number } | null>(null);
  const movedRef = useRef(false);
  return (
    <Group
      x={n.pos.x}
      y={n.pos.y}
      listening
      onMouseDown={(e) => {
        const p = e.target.getStage()!.getPointerPosition()!;
        downRef.current = p; movedRef.current = false; setDragging(true);
        onDragStart(p);
      }}
      onMouseMove={(e) => {
        if (!dragging || !downRef.current) return;
        const p = e.target.getStage()!.getPointerPosition()!;
        const dx = p.x - downRef.current.x, dy = p.y - downRef.current.y;
        if (!movedRef.current && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) movedRef.current = true;
        onDragMove(p);
      }}
      onMouseUp={() => {
        onDragEnd(movedRef.current);
        setDragging(false); downRef.current = null; movedRef.current = false;
      }}
    >
      <Rect width={n.size.w} height={K.headerHeight} fill="#5aa9e6" stroke="#1c7ed6" strokeWidth={2} />
      <Text text={n.title} x={24} y={9} fontFamily="Helvetica" fontSize={12} fontStyle="bold" fill="#0b2e4e" />
      {/* triangle indicator */}
      <Text text={n.expanded ? '▼' : '▶'} x={6} y={8} fontSize={12} fill="#0b2e4e"
        onClick={() => onToggle()} />
    </Group>
  );
}

function NodeView({ n }: { n: BaseNode }) {
  const moveNode = useGraph(s => s.moveNode);
  const resizeNode = useGraph(s => s.resizeNode);
  const toggle = useGraph(s => s.toggleExpand);
  const [dragBase, setDragBase] = useState<{ x: number; y: number } | null>(null);

  const visible = n.kind === 'act' || n.expanded;

  return (
    <Group key={n.id} zIndex={zIndexFor(n.kind)} listening={visible}>
      <Header n={n}
        onToggle={() => toggle(n.id)}
        onDragStart={(p) => setDragBase(p)}
        onDragMove={(p) => {
          if (!dragBase) return;
          const dx = p.x - dragBase.x, dy = p.y - dragBase.y;
          setDragBase(p);
          moveNode(n.id, dx, dy);
        }}
        onDragEnd={(wasDrag) => {
          if (!wasDrag) toggle(n.id);
        }}
      />
      {/* body */}
      {n.expanded && (
        <Group x={n.pos.x} y={n.pos.y}>
          <Rect y={K.headerHeight} width={n.size.w} height={n.size.h - K.headerHeight}
            fill={n.kind === 'beat' ? '#b2e3ff' : n.kind === 'step' ? '#c9ecff' : n.kind === 'sequence' ? '#a8defc' : '#7ec3ff'}
            stroke="#1c7ed6" strokeWidth={2} />
          <Text text={n.body} x={12} y={K.headerHeight + 12} width={n.size.w - 24} fill="#0b2e4e" />
          {/* resize handle */}
          <Rect x={n.size.w - 8} y={n.size.h - 8} width={12} height={12} fill="#333"
            draggable
            dragBoundFunc={(pos) => pos}
            onDragMove={(e) => {
              const p = e.target.position();
              const w = Math.max(120, p.x + 8); const h = Math.max(80, p.y + 8);
              resizeNode(n.id, w, h);
            }}
          />
        </Group>
      )}
    </Group>
  );
}

export default function CanvasStage() {
  const nodes = useGraph(s => Object.values(s.nodes));
  const stageRef = useRef<Konva.Stage>(null);
  return (
    <Stage ref={stageRef} width={1400} height={900} style={{ background: '#f6f6f6' }}>
      <Layer>
        {nodes.map(n => <NodeView key={n.id} n={n} />)}
      </Layer>
    </Stage>
  );
}
