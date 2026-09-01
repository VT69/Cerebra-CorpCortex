"""
RAG with LangGraph — Beginner's Guide

The difference from basic rag.py:
  Basic RAG  = sequential function calls (step 1 → step 2 → step 3)
  LangGraph  = a STATE MACHINE where each step is a NODE in a graph

Why does this matter?
  - You can ADD/REMOVE steps without rewriting everything
  - You can ADD CONDITIONAL BRANCHES ("if confidence is low, search again")
  - The graph is INSPECTABLE — you can visualize it, trace it, debug it
  - This is EXACTLY how Cerebra's supervisor.py works!

LangGraph Core Concepts:
  STATE  — A dictionary that flows through every node (like a shared notebook)
  NODE   — A function that reads the state and returns updated values
  EDGE   — A connection between two nodes (can be conditional!)
  GRAPH  — The compiled workflow you invoke at the end
"""

import os
from typing import TypedDict, List
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

os.environ["GROQ_API_KEY"] = "your_groq_api_key_here"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 0: One-time setup — Build the Vector Store (Ingestion Phase)
# This runs ONCE to build the "library". In production, this is pre-built.
# ─────────────────────────────────────────────────────────────────────────────

def build_vector_store():
    with open("dummy_knowledge.txt", "w") as f:
        f.write("The secret passcode for the server room is 8492.\n\n")
        f.write("The CEO of CorpCortex is Jane Doe.\n\n")
        f.write("Project Phoenix launches on October 15th, 2025.\n\n")
        f.write("The office Wi-Fi password is CorpNet@2024.\n\n")

    loader = TextLoader("dummy_knowledge.txt")
    documents = loader.load()
    chunks = CharacterTextSplitter(chunk_size=60, chunk_overlap=0).split_documents(documents)
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return Chroma.from_documents(chunks, embeddings)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Define the STATE
#
# This is the most important concept in LangGraph.
# Think of it as a shared notebook passed between every node.
# Each node reads from it and writes back to it.
# ─────────────────────────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str           # The user's question (set at the start)
    retrieved_docs: List[str]  # Retrieved text chunks (set by retrieve_node)
    answer: str             # Final answer (set by generate_node)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Define the NODES (each node is just a Python function)
#
# Rules:
#   - Takes the full state as input
#   - Returns a DICT of only the keys it wants to update
# ─────────────────────────────────────────────────────────────────────────────

def retrieve_node(state: RAGState) -> dict:
    """
    NODE 1: Retrieval
    Reads:  state["question"]
    Writes: state["retrieved_docs"]
    """
    print(f"\n[NODE: retrieve] Searching for: '{state['question']}'")

    results = vector_store.similarity_search(state["question"], k=2)
    texts = [doc.page_content for doc in results]

    print(f"[NODE: retrieve] Found {len(texts)} relevant chunk(s)")
    for i, t in enumerate(texts):
        print(f"  Chunk {i+1}: '{t}'")

    # Return only the key(s) this node updates
    return {"retrieved_docs": texts}


def generate_node(state: RAGState) -> dict:
    """
    NODE 2: Generation
    Reads:  state["question"], state["retrieved_docs"]
    Writes: state["answer"]
    """
    print(f"\n[NODE: generate] Building prompt and calling LLM...")

    # Join all retrieved chunks into one context block
    context = "\n".join(state["retrieved_docs"])

    prompt_template = PromptTemplate.from_template("""
    You are a helpful assistant. Use ONLY the following context to answer.
    If you don't know, say "I don't know."

    Context:
    {context}

    Question: {question}
    Answer:""")

    prompt = prompt_template.format(
        context=context,
        question=state["question"]
    )

    llm = ChatGroq(
        api_key=os.environ["GROQ_API_KEY"],
        model_name="qwen/qwen3.6-27b",
        temperature=0
    )
    response = llm.invoke(prompt)

    return {"answer": response.content}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Build the GRAPH
#
# This is where you wire nodes together with edges.
# Think of it like drawing a flowchart.
# ─────────────────────────────────────────────────────────────────────────────

def build_rag_graph():
    # 1. Create the graph, telling it what State shape to use
    graph = StateGraph(RAGState)

    # 2. Register nodes (name → function)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)

    # 3. Set the entry point (where the graph starts)
    graph.set_entry_point("retrieve")

    # 4. Add edges (the arrows between nodes)
    graph.add_edge("retrieve", "generate")  # retrieve → generate
    graph.add_edge("generate", END)          # generate → done

    # 5. Compile and return the runnable graph
    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Run it!
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Building vector store (Ingestion Phase) ===")
    vector_store = build_vector_store()

    print("\n=== Building LangGraph RAG pipeline ===")
    rag_graph = build_rag_graph()

    # The graph takes an initial state dict and runs all nodes
    questions = [
        "What is the secret passcode for the server room?",
        "Who is the CEO?",
        "When does Project Phoenix launch?",
    ]

    for question in questions:
        print(f"\n{'='*60}")
        print(f"QUESTION: {question}")

        # Invoke the graph with the initial state
        # LangGraph runs: retrieve_node → generate_node → END
        final_state = rag_graph.invoke({"question": question})

        print(f"\n[FINAL ANSWER]: {final_state['answer']}")
