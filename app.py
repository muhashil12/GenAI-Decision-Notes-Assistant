import os
import io

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from decimal import Decimal
import streamlit as st  # type: ignore
from PyPDF2 import PdfReader  # type: ignore

from langchain.output_parsers import PydanticOutputParser  # type: ignore
from langchain.prompts import ChatPromptTemplate  # type: ignore
from langchain_core.output_parsers.string import StrOutputParser  # type: ignore
from langchain.callbacks.base import BaseCallbackHandler  # type: ignore
from langchain_openai import ChatOpenAI  # type: ignore

from dotenv import load_dotenv  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

from typing import List

from prompts import *

load_dotenv(".env")


class StreamHandler(BaseCallbackHandler):
    def __init__(self, container, initial_text=""):
        self.container = container
        self.text = initial_text

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.text += token
        self.container.markdown(self.text)


class KYCErrors(BaseModel):
    error: str = Field(..., description="Error reason")


class KYCResult(BaseModel):
    is_valid: bool = Field(..., description="Boolean KYC is valid or not")
    errors: List[KYCErrors]


def read_file(file):
    # Check if file is an image or PDF
    if file.type.startswith("image/"):
        # Handle image files
        image = Image.open(io.BytesIO(file.read()))
        text = pytesseract.image_to_string(image, lang="ind")
    elif file.type == "application/pdf":
        # Handle PDF files
        reader = PdfReader(file)
        text = ""
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            text += page.extract_text()
    return text


def analyze_ktp(llm, output_parser, inputs, content):
    prompt = ChatPromptTemplate.from_template(role="system", template=KTP_KYC_PROMPT)
    prompt = prompt.partial(format_instructions=output_parser.get_format_instructions())
    runnable = prompt | llm | output_parser
    return runnable.invoke({"content": content, **inputs})


def analyze_proof_of_income(llm, output_parser, inputs, content):
    prompt = ChatPromptTemplate.from_template(role="system", template=POI_KYC_PROMPT)
    prompt = prompt.partial(format_instructions=output_parser.get_format_instructions())
    runnable = prompt | llm | output_parser
    return runnable.invoke({"content": content, **inputs})


def analyze_student_school_assessment(llm, output_parser, inputs, content):
    prompt = ChatPromptTemplate.from_template(role="system", template=SCHOOL_ASSESSMENT_KYC_PROMPT)
    prompt = prompt.partial(format_instructions=output_parser.get_format_instructions())
    runnable = prompt | llm | output_parser
    return runnable.invoke({"content": content, **inputs})


def main():
    llm = ChatOpenAI(model="gpt-4o", temperature=0)

    # Streamlit
    st.title("Loan Application Form")

    # Input fields
    name = st.text_input("Full Name")
    nik = st.text_input("ID Card Number")
    school_name = st.text_input("School")

    ktp_file = st.file_uploader("ID Card", type=["jpg", "jpeg", "png"])
    proof_of_income_file = st.file_uploader(
        "Proof Of Income", type=["jpg", "jpeg", "png", "pdf"]
    )
    school_assessment_file = st.file_uploader(
        "School Assessment", type=["jpg", "jpeg", "png", "pdf"]
    )

    loan_tenor = st.number_input("Tenor (month)", min_value=0)
    loan_interest_rate = st.number_input(
        "Interest Rate (%)", min_value=0.0, format="%.2f"
    )
    loan_penalty_rate = st.number_input(
        "Penalty Rate (%)", min_value=0.0, format="%.2f"
    )
    loan_requested_principal = st.number_input(
        "Requested Principal (IDR)", min_value=0.0, format="%.2f"
    )

    # Button to submit the form
    if st.button("Submit"):
        if not all(
            [
                name,
                nik,
                ktp_file,
                school_name,
                loan_tenor,
                loan_interest_rate,
                loan_penalty_rate,
                loan_requested_principal,
                proof_of_income_file,
                school_assessment_file,
            ]
        ):
            st.error("Please fill in all the fields and upload all required files.")

        with st.spinner("Please wait.."):
            ktp_content: str = read_file(ktp_file)
            income_proof_content: str = read_file(proof_of_income_file)
            school_assessment_content: str = read_file(school_assessment_file)

            inputs = {
                "name": name,
                "nik": nik,
                "school_name": school_name,
                "loan_tenor": loan_tenor,
                "loan_interest_rate": loan_interest_rate,
                "loan_penalty_rate": loan_penalty_rate,
                "loan_requested_principal": loan_requested_principal,
            }

            output_parser = PydanticOutputParser(pydantic_object=KYCResult)

            ktp_result: KYCResult = analyze_ktp(llm, output_parser, inputs, ktp_content)
            poi_result: KYCResult = analyze_proof_of_income(
                llm, output_parser, inputs, income_proof_content
            )
            school_assessment_result: KYCResult = analyze_student_school_assessment(
                llm, output_parser, inputs, school_assessment_content
            )

            decisions_data = {
                "ktp_valid": ktp_result.is_valid,
                "ktp_errors": [error.error for error in ktp_result.errors],
                "poi_valid": poi_result.is_valid,
                "poi_errors": [error.error for error in poi_result.errors],
                "school_assessment_valid": school_assessment_result.is_valid,
                "school_assessment_errors": [
                    error.error for error in school_assessment_result.errors
                ],
                "loan_tenor": loan_tenor,
                "loan_interest_rate": loan_interest_rate,
                "loan_penalty_rate": loan_penalty_rate,
                "loan_requested_principal": loan_requested_principal,
                "total_loans_internal": 3,
                "total_npl_loans_internal": 1,
                "total_closed_loans_internal": 2,
                "score_internal": 75,
                "total_loans_external": 1,
                "total_npl_loans_external": 0,
                "total_closed_loans_external": 1,
                "score_external": 100,
            }

            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", DECISION_NOTES_PROMPT),
                    ("human", HUMAN_PROMPT),
                ]
            )
            runnable = prompt | llm | StrOutputParser()
            resp = runnable.invoke(decisions_data)
            st.markdown(resp)


if __name__ == "__main__":
    main()
