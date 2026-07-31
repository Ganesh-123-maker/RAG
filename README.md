# RAG - Retrieval-Augmented Generation

A Retrieval-Augmented Generation (RAG) application developed by **Barmavath Ganesh** that enables users to ask questions based on uploaded documents. The system retrieves the most relevant document chunks using semantic search and generates accurate, context-aware answers with a Large Language Model (LLM).

---

## 🚀 Features

- 📄 Upload PDF, DOCX, and TXT documents
- 🔍 Semantic document retrieval using vector embeddings
- 🤖 AI-powered question answering with LLMs
- ⚡ Fast similarity search using FAISS
- 🧠 Context-aware responses
- 💬 Simple and responsive web interface
- ☁️ Deployable on Railway

---

## 🛠️ Tech Stack

| Category | Technologies |
|----------|--------------|
| Programming Language | Python |
| Backend | FastAPI |
| AI Framework | LangChain |
| LLM | OpenAI GPT / Google Gemini |
| Embedding Model | Hugging Face Embeddings |
| Vector Database | FAISS |
| Frontend | HTML, CSS, JavaScript |
| Server | Uvicorn |
| Deployment | Railway |
| Version Control | Git & GitHub |

---

## 📂 Project Structure

```
RAG/
│── app.py
│── requirements.txt
│── README.md
│── .env
│── uploads/
│── vectorstore/
│── static/
│── templates/
│── utils/
└── data/
```

---

## ⚙️ Installation

### Clone the Repository

```bash
git clone https://github.com/Ganesh-123-maker/RAG.git
cd RAG
```

### Create a Virtual Environment

```bash
python -m venv venv
```

### Activate the Environment

**Windows**

```bash
venv\Scripts\activate
```

**Linux/macOS**

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Create a `.env` file.

For OpenAI:

```env
OPENAI_API_KEY=your_openai_api_key
```

or for Gemini:

```env
GEMINI_API_KEY=your_gemini_api_key
```

### Run the Project

```bash
uvicorn app:app --reload
```

or

```bash
python app.py
```

---

## 💡 How It Works

1. Upload one or more documents.
2. Documents are split into smaller chunks.
3. Embeddings are generated for every chunk.
4. Embeddings are stored in a FAISS vector database.
5. The user's query is converted into an embedding.
6. Similar document chunks are retrieved.
7. Retrieved context is sent to the LLM.
8. The model generates an accurate answer based on the retrieved information.

---

## 🎯 Use Cases

- AI-powered document search
- Research assistance
- Knowledge base chatbot
- Company documentation assistant
- Educational Q&A system
- Technical document analysis

---

## 📈 Future Enhancements

- Multi-document support
- Conversation memory
- Source citations
- User authentication
- Chat history
- Hybrid search
- Cloud storage integration

---

## 👨‍💻 Developer

**Barmavath Ganesh**

- **B.Tech Computer Science and Engineering**
- **Indian Institute of Information Technology Guwahati (IIIT Guwahati)**
- **Location:** Hyderabad, Telangana, India

### Connect with Me

- **GitHub:** https://github.com/Ganesh-123-maker
- **LinkedIn:** https://www.linkedin.com/in/barmavathganesh
- **Email:** ganeshbarmavath14@gmail.com

---

## 📄 License

This project is licensed under the **MIT License**.

---

⭐ If you found this project useful, please consider giving it a **Star** on GitHub.
