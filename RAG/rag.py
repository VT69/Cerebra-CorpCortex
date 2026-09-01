"""
A Beginner's Guide to RAG (Retrieval-Augmented Generation)

This script demonstrates the absolute core components of a RAG pipeline.
We've updated this to use your Groq API key for insanely fast generation,
and local HuggingFace embeddings (free, runs on your CPU).
"""
import os
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings # Local embeddings
from langchain_groq import ChatGroq  # Official Groq integration — much cleaner!
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import PromptTemplate


# Set your Groq API Key
os.environ["GROQ_API_KEY"] = "your_groq_api_key_here"

def run_simple_rag():
    print("=== Phase 1: Ingestion ===")
    
    # 1. Load Data
    with open("dummy_knowledge.txt", "w") as f:
        f.write("The secret passcode for the server room is 8492.\n\n")
        f.write("The CEO of CorpCortex is Jane Doe.\n\n")
        f.write("Project Phoenix launches on October 15th, 2025.\n\n")
    
    print("1. Loading documents...")
    loader = TextLoader("dummy_knowledge.txt")
    documents = loader.load()

    # 2. Chunking (Splitting)
    print("2. Chunking documents...")
    text_splitter = CharacterTextSplitter(chunk_size=50, chunk_overlap=0)
    chunks = text_splitter.split_documents(documents)
    
    # 3. Embeddings & Vector Store
    # We use sentence-transformers to create local embeddings so we don't need an OpenAI key
    print("3. Creating local embeddings and storing in VectorDB...\n")
    embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma.from_documents(chunks, embeddings_model)

    
    print("=== Phase 2: Retrieval ===")
    
    user_question = "Who is CEO of CorpCortex?"
    print(f"User Question: '{user_question}'")
    
    # 4. Search the Vector Store
    retriever = vector_store.as_retriever(search_kwargs={"k": 1})
    retrieved_docs = retriever.invoke(user_question)
    
    retrieved_text = retrieved_docs[0].page_content
    print(f"Retrieved Context: '{retrieved_text}'\n")


    print("=== Phase 3: Generation ===")
    
    # 5. Build the Prompt
    prompt_template = """
    You are a helpful assistant. Use ONLY the following context to answer the question.
    If the context doesn't contain the answer, say "I don't know."

    Context:
    {context}

    Question:
    {question}

    Answer:
    """
    prompt = PromptTemplate.from_template(prompt_template)
    final_prompt = prompt.format(context=retrieved_text, question=user_question)
    print("Constructed Prompt sent to LLM:\n", final_prompt)

    # 6. Generate Answer using Groq (official langchain_groq integration)
    print("Generating answer using Groq (qwen/qwen3.6-27b)...")
    llm = ChatGroq(
        api_key=os.environ["GROQ_API_KEY"],
        model_name="qwen/qwen3.6-27b",
        temperature=0
    )
    response = llm.invoke(final_prompt)
    
    print("\n=== Final Output ===")
    print(response.content)

if __name__ == "__main__":
    run_simple_rag()
