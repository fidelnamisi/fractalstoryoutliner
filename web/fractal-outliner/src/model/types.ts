export type NodeKind = 'act' | 'sequence' | 'step' | 'beat';

export interface Size { w: number; h: number }
export interface Point { x: number; y: number }

export interface BaseNode {
  id: string;
  kind: NodeKind;
  title: string;
  body: string;
  pos: Point; // absolute position of the node's outer rect
  size: Size; // outer size
  headerHeight: number;
  expanded: boolean;
  attachedToParent: boolean;
  relativeOffset?: Point; // offset from parent.innerTopLeft when attached
  parentId?: string;
  childIds: string[];
}

export interface GraphState {
  nodes: Record<string, BaseNode>;
  rootId: string; // Act id
}

export const K = {
  headerHeight: 36,
  innerPad: 12,
  outerGap: 20,
  beatGap: 12,
} as const;
