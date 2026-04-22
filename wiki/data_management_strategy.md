# Product Data Management & Integration Strategy

To ensure efficient retrieval of the complete product catalog and descriptions without exceeding token limits, the following integration methods are established:

## 1. Knowledge Base Upload (Primary)
- **Method:** Export product catalog (Shopify/WooCommerce/ERP) as **CSV or JSON**.
- **Implementation:** Upload directly to the platform's knowledge base/system instructions.
- **Benefit:** Enables Retrieval-Augmented Generation (RAG) for silent, accurate searching of bilingual specs without consuming chat history.

## 2. API & Tool Integration (Advanced)
- **Method:** Connect to live databases (Airtable, Google Sheets, or e-commerce backend) via API endpoints.
- **Tooling:** Use `fetch_product_data(sku)` via Zapier, Make, or custom function calling.
- **Benefit:** Real-time access to pricing, inventory levels, and descriptions during campaign drafting.

## 3. Compressed Markdown Wiki (Fallback)
- **Method:** Convert heavy JSON arrays into high-density, token-efficient Markdown lists.
- **Benefit:** Reduces memory usage by approximately 50% compared to raw JSON, maximizing space for strategic planning and copywriting.