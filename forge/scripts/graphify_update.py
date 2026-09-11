import os
import json
import networkx as nx

GRAPH_FILE = ".graphify/graphify_db.json"
ROOT_DIR = "."

def build_graph():
    G = nx.Graph()
    G.add_node("athanor", type="root", description="Athanor OS Core Repository")
    
    # Scan major directories
    for root, dirs, files in os.walk(ROOT_DIR):
        # Exclude hidden and build dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'node_modules', 'RPMS_OUT']]
        
        rel_root = os.path.relpath(root, ROOT_DIR)
        if rel_root == ".":
            parent = "athanor"
        else:
            parent = os.path.basename(rel_root)
            
        for d in dirs:
            G.add_node(d, type="module", path=os.path.join(rel_root, d))
            G.add_edge(parent, d, relation="contains")
            
        for f in files:
            if f.endswith('.rs') or f.endswith('.md') or f.endswith('.json') or f.endswith('.sh') or f.endswith('Justfile'):
                file_node = f"{parent}/{f}"
                G.add_node(file_node, type="file", path=os.path.join(rel_root, f))
                G.add_edge(parent, file_node, relation="implements")

    return G

def save_graph(G):
    from networkx.readwrite import json_graph
    data = json_graph.node_link_data(G)
    os.makedirs(os.path.dirname(GRAPH_FILE), exist_ok=True)
    with open(GRAPH_FILE, 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    print("Graphify indexing started...")
    G = build_graph()
    save_graph(G)
    print(f"Graphify synchronization complete! Indexed {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
