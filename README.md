# CAGE Distance Explorer

A Streamlit app that uses the Gemini API with Google Search grounding to research a country pair, assigns 1–5 CAGE dimension scores, explains industry-specific weights, and tests weight sensitivity.

## Deploy using GitHub and Streamlit Community Cloud

1. Create a GitHub repository, e.g. `cage-distance-explorer`.
2. Add `app.py` and `requirements.txt` to the **repository root**. Do not upload an API key.
3. At https://share.streamlit.io/ create an app from the GitHub repository. Set the main file to `app.py`.
4. In **Advanced settings → Secrets**, enter:

   ```toml
   GEMINI_API_KEY = "YOUR_PRIVATE_KEY_HERE"
   ```

5. Deploy. Try **United States → Japan** and **Video game retail**. Check each citation and the sensitivity results.
6. Open the Streamlit app URL in a private/incognito browser window to confirm that graders do not need to log in.
7. Create a PDF with (1) the public link at the top, (2) the actual verified app output including sources/weights/recommendation/sensitivity, and (3) a 250–500 word reflection.

## Caveats

- CAGE scores and weights are **judgments**, not official country measures.
- Grounded search results should be checked independently; a search-grounded URL does not automatically validate every AI-generated number or claim.
- Gemini free-tier quotas, model availability, and grounding features can change. If one model is unavailable, choose the other in the app.
- The app never asks public visitors for an API key; traffic uses the deployer's private quota. Public usage should be monitored.
