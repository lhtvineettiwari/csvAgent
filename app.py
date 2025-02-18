import streamlit as st
import pandas as pd
from pymongo import MongoClient
import json
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

class QueryAgent:
    """Agent responsible for converting natural language queries into MongoDB queries."""
    
    def __init__(self, available_fields: list[str], sample_data: dict):
        self.available_fields = available_fields
        self.field_descriptions = {
            field: f"Example value: {sample_data[field]}" 
            for field in available_fields
        }
        
        self.llm = ChatOpenAI(temperature=0, model="gpt-3.5-turbo")
        
        # Generic system prompt that adapts to any CSV structure
        self.system_prompt = f"""You are an intelligent assistant that helps users find information in a CSV dataset by converting natural language questions into MongoDB queries.

Available fields and example values:
{self._format_field_descriptions()}

Your task is to:
1. Understand the user's natural language question
2. Figure out their true intent (what information they want)
3. Create the appropriate MongoDB query using the available fields

Query patterns:
1. Finding records by field value:
   {{"filter": {{"field_name": {{"$regex": "value", "$options": "i"}}}}, "fields": ["relevant_fields"]}}

2. Counting records:
   {{"filter": {{"field_name": {{"$regex": "value", "$options": "i"}}}}, "operation": "count"}}

3. Computing averages:
   {{"pipeline": [{{"$group": {{"_id": null, "average": {{"$avg": "$field_name"}}}}}}]}}

Remember:
1. Use exact field names from the available fields list
2. Always use case-insensitive regex for text searches
3. Include relevant fields in the response based on the question
4. Return only the fields that would help answer the question
5. Use proper MongoDB query operators

Think step by step:
1. What information is the user looking for?
2. Which fields in the data would have this information?
3. What's the best way to query these fields?
4. What fields should be included in the response?

Guidelines:
- For text searches, use case-insensitive regex matching
- For numeric fields, use appropriate comparison operators
- Include fields that provide context to the answer
- Use the exact field names shown above
- Structure queries based on the patterns shown above

First, explain your thinking step by step.
Then output the MongoDB query object as valid JSON.
Format your response as:
THINKING: your step-by-step analysis
QUERY: the JSON query object"""

    def _format_field_descriptions(self) -> str:
        """Format field descriptions for the system prompt."""
        return "\n".join([f"- {field}: {desc}" for field, desc in self.field_descriptions.items()])

    def formulate_query(self, user_question: str) -> tuple[str, str]:
        """Convert user's natural language question into a MongoDB query."""
        st.write("🤔 Understanding the question:", user_question)
        
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_question)
        ]
        
        st.write("🔄 Sending to LLM with available fields:", ", ".join(self.available_fields))
        response = self.llm.invoke(messages)
        content = response.content.strip()
        
        # Split thinking and query
        parts = content.split("QUERY:")
        if len(parts) == 2:
            thinking = parts[0].replace("THINKING:", "").strip()
            query = parts[1].strip()
        else:
            thinking = "No explicit thinking provided"
            query = content
        
        st.write("🧠 LLM's Thinking Process:")
        for i, step in enumerate(thinking.split("\n"), 1):
            if step.strip():
                st.write(f"  {i}. {step.strip()}")
        
        # Clean any markdown formatting from query
        if query.startswith("```") and query.endswith("```"):
            query = "\n".join(query.split("\n")[1:-1])
        if query.startswith("json"):
            query = query[4:].strip()
            
        st.write("📝 Generated Query:", query)
        
        try:
            # Validate JSON
            json_query = json.loads(query)
            st.write("✅ Query validation: Valid JSON")
            
            # Log query structure
            if "filter" in json_query:
                st.write("🔍 Filter conditions:", json_query["filter"])
            if "fields" in json_query:
                st.write("📋 Requested fields:", json_query["fields"])
            if "pipeline" in json_query:
                st.write("🔄 Aggregation pipeline:", json_query["pipeline"])
            if "operation" in json_query:
                st.write("⚡ Special operation:", json_query["operation"])
                
        except json.JSONDecodeError as e:
            st.error(f"❌ Query validation failed: {str(e)}")
        
        return query

def execute_query(collection, query: str) -> str:
    """Execute MongoDB query and return results."""
    try:
        # Parse the query string into a dict
        query_obj = json.loads(query)
        st.write("🚀 Executing query:", json.dumps(query_obj, indent=2))
        
        # Execute the appropriate query type
        if "operation" in query_obj and query_obj["operation"] == "count":
            filter_query = query_obj.get("filter", {})
            st.write("🔢 Counting documents with filter:", filter_query)
            count = collection.count_documents(filter_query)
            return f"Found {count} records"
            
        elif "pipeline" in query_obj:
            st.write("📊 Running aggregation pipeline:", json.dumps(query_obj["pipeline"], indent=2))
            result = list(collection.aggregate(query_obj["pipeline"]))
            return json.dumps(result, indent=2)
            
        else:
            # Regular find query
            filter_query = query_obj.get("filter", {})
            # Get specific fields if requested
            fields = query_obj.get("fields", None)
            projection = {field: 1 for field in fields} if fields else None
            
            st.write("🔍 Search filter:", json.dumps(filter_query, indent=2))
            if projection:
                st.write("📋 Returning fields:", list(projection.keys()))
            
            # Execute find with optional projection
            if projection:
                st.write("🎯 Using field projection:", projection)
                matches = list(collection.find(filter_query, projection))
            else:
                st.write("📄 Returning all fields")
                matches = list(collection.find(filter_query))
            
            st.write(f"✨ Found {len(matches)} matches")
            
            if not matches:
                return "No matching records found"
            
            # Format results
            result = []
            for doc in matches:
                doc.pop('_id', None)
                formatted_details = "\n".join([f"  {k}: {v}" for k, v in doc.items()])
                result.append(f"Record:\n{formatted_details}")
            
            return f"Found {len(matches)} matches:\n\n" + "\n\n".join(result)

    except Exception as e:
        st.error(f"❌ Error processing query: {str(e)}")
        return f"Error processing query: {str(e)}"

def main():
    st.set_page_config(page_title="CSV QnA Agent", layout="wide")
    
    st.title("CSV Question & Answer Agent")
    st.write("Upload your CSV file and ask questions about your data!")

    # File uploader
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

    if uploaded_file is not None:
        # Read CSV
        with st.spinner("📂 Reading CSV file..."):
            df = pd.read_csv(uploaded_file)
            st.success(f"✅ Successfully read CSV with {len(df)} rows")
        
        # Show data preview
        with st.expander("👀 Preview Data"):
            st.dataframe(df.head())
            
        # Connect to MongoDB
        with st.spinner("🔌 Connecting to MongoDB..."):
            client = MongoClient("mongodb://localhost:27017")
            db = client["csvAgent"]
            collection = db["csv_data"]
            
            # Clear existing data
            collection.delete_many({})
            
            # Load data into MongoDB
            records = df.to_dict("records")
            collection.insert_many(records)
            st.success(f"✅ Loaded {len(records)} records into MongoDB")
        
        # Get schema info
        available_fields = list(df.columns)
        sample_data = df.head(1).to_dict('records')[0]
        
        # Initialize agent
        agent = QueryAgent(available_fields, sample_data)
        
        # Show available fields
        with st.expander("📋 Available Fields"):
            st.write(", ".join(available_fields))
            st.write("📝 Sample Data:")
            st.json(sample_data)
        
        # Question input
        question = st.text_input("❓ Ask a question about your data:")
        
        if question:
            st.divider()
            
            # Create columns for showing process
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🔄 Query Processing")
                with st.spinner("🤔 Formulating query..."):
                    # Get query from agent
                    query = agent.formulate_query(question)
                    st.success("✅ Query formulated")
                    # Show formatted query
                    st.code(query, language="json")
            
            with col2:
                st.subheader("📊 Results")
                with st.spinner("🚀 Executing query..."):
                    # Execute query and show results
                    results = execute_query(collection, query)
                    st.success("✅ Query executed")
                    st.text(results)

if __name__ == "__main__":
    main()
