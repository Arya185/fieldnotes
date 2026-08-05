import type { ConceptMapResponse } from "../types";

interface ConceptMapViewProps {
  graph: ConceptMapResponse;
  onNodeClick: (sourceAnchor: string | undefined) => void;
}

const SIZE = 420;
const CENTER = SIZE / 2;
const RADIUS = SIZE / 2 - 56;

function nodeColor(state: string): string {
  return state === "shaky" ? "#b45309" : "#1768ac";
}

function nodeFill(state: string): string {
  return state === "shaky" ? "rgba(217, 119, 6, 0.16)" : "rgba(23, 104, 172, 0.12)";
}

export function ConceptMapView({ graph, onNodeClick }: ConceptMapViewProps) {
  const positions = new Map<string, { x: number; y: number }>();
  const count = Math.max(graph.nodes.length, 1);
  graph.nodes.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / count - Math.PI / 2;
    positions.set(node.id, {
      x: CENTER + RADIUS * Math.cos(angle),
      y: CENTER + RADIUS * Math.sin(angle),
    });
  });

  const maxWeight = Math.max(1, ...graph.edges.map((edge) => edge.weight));

  return (
    <div className="concept-map-view">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Concept map of related concepts">
        <g>
          {graph.edges.map((edge, index) => {
            const source = positions.get(edge.source);
            const target = positions.get(edge.target);
            if (!source || !target) {
              return null;
            }
            return (
              <line
                key={`${edge.source}-${edge.target}-${index}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke="rgba(20, 32, 43, 0.25)"
                strokeWidth={1 + (edge.weight / maxWeight) * 3}
              />
            );
          })}
        </g>
        <g>
          {graph.nodes.map((node) => {
            const position = positions.get(node.id);
            if (!position) {
              return null;
            }
            return (
              <g
                key={node.id}
                transform={`translate(${position.x}, ${position.y})`}
                className="concept-map-node"
                role="button"
                tabIndex={node.source_anchor ? 0 : -1}
                aria-label={`${node.name}: ${node.state}. ${node.source_anchor ? "Jump to source." : "No source available."}`}
                onClick={() => onNodeClick(node.source_anchor)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    onNodeClick(node.source_anchor);
                  }
                }}
              >
                <circle r={16} fill={nodeFill(node.state)} stroke={nodeColor(node.state)} strokeWidth={2} />
                <text textAnchor="middle" dy={32} fontSize={12} fill="var(--ink, #14202b)">
                  {node.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="concept-map-legend">
        <span className="pill">{graph.nodes.length} concepts</span>
        <span className="pill">{graph.edges.length} connections</span>
        <span className="pill shaky">shaky</span>
        <span className="pill">touched</span>
      </div>
    </div>
  );
}
