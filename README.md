# 論文スライド自動生成 README（人がやることだけ）

このフォルダでは、論文引用リストから `papers.json` を作り、作成済みの `template.pptx` に流し込んで PowerPoint を生成します。

---

## 0. 前提

PowerPointのテンプレートは、すでに作成済みの `template.pptx` を使います。

`template.pptx` には以下のプレースホルダーが入っている前提です。

```text
{{jp_title}}
{{authors}}
{{affiliations}}
{{journal_doi}}
{{en_title}}
{{pubmed_info}}
{{background}}
{{methods}}
{{results}}
{{conclusion}}
{{paper_no}}
```

`{{paper_no}}` はPython側で自動的に `論文1`, `論文2`, ... と入ります。  
ChatGPTに作らせる `papers.json` には `paper_no` を入れません。

---

## 1. フォルダに置くファイル

作業フォルダはこのようにします。

```text
paper_slide_project/
  template.pptx

  input_raw.txt
  prompt_create_papers_json.txt

  raw_to_input_papers_csv_v3.py
  pmid_pmcid_to_authors_affiliations.py
  make_paper_slides_powerpoint.py

  papers.json
```

| ファイル | 役割 |
|---|---|
| `template.pptx` | 既に作成済みのPowerPointテンプレート |
| `input_raw.txt` | 論文引用リストをそのまま貼るファイル |
| `prompt_create_papers_json.txt` | ChatGPTに渡すプロンプト |
| `raw_to_input_papers_csv_v3.py` | `input_raw.txt` から PMID / PMCID / DOI を抽出 |
| `pmid_pmcid_to_authors_affiliations.py` | PubMed / PMC XMLから authors / affiliations を抽出 |
| `make_paper_slides_powerpoint.py` | `papers.json` を `template.pptx` に流し込む |
| `papers.json` | ChatGPTが作成するPowerPoint差し込み用JSON |

---

## 2. 毎回の作業手順

### Step 1. `input_raw.txt` に論文リストを貼る

`input_raw.txt` を開いて、論文引用リストをそのまま貼ります。

例：

```text
論文1：
Phuong J, Hong S, Palchuk MB, Espinoza J, Meeker D, Dorr DA, et al. Advancing Interoperability of Patient-level Social Determinants of Health Data to Support COVID-19 Research. AMIA Jt Summits Transl Sci Proc. 2022;2022:396–405. PubMed PMID: 35854720; PubMed Central PMCID: PMC9285174.

論文2：
Pasha A, Qiao S, Zhang J, Cai R, He B, Yang X, et al. The impact of the COVID-19 pandemic on mental health care utilization among people living with HIV: A real-world data study. medRxiv. 2024. doi:10.1101/2024.09.26.24314443 PubMed PMID: 39398989; PubMed Central PMCID: PMC11469454.
```

ポイント：

- `論文1：`, `論文2：` のように番号を付ける
- できれば論文ごとに空行を入れる
- PMID / PMCID / DOI がある場合は、そのまま残す

---

### Step 2. PMID / PMCID / DOI を抽出する

VS Codeのターミナルで実行します。

```powershell
python raw_to_input_papers_csv_v3.py input_raw.txt input_papers.csv
```

成功すると `input_papers.csv` ができます。

実行後に表示される `Extracted records:` が論文本数と合っているか確認します。

例：

```text
Extracted records: 10
```

論文が10本なら `10`、9本なら `9` になっていればOKです。

---

### Step 3. 著者・所属CSVを作る

続けて実行します。

```powershell
python pmid_pmcid_to_authors_affiliations.py input_papers.csv authors_affiliations.csv
```

成功すると以下ができます。

```text
authors_affiliations.csv
authors_affiliations_summary.csv
```

次に見るのは `authors_affiliations_summary.csv` です。

確認する列：

```text
authors
affiliations
warnings
```

`warnings` に何か入っている論文は、所属情報が不完全な可能性があります。  
ただし、`authors` と `affiliations` に値が入っていれば、基本的にはその値を使います。

---

### Step 4. ChatGPTで `papers.json` を作る

1. `prompt_create_papers_json.txt` を開く
2. 中身をChatGPTに貼る
3. `authors_affiliations_summary.csv` を添付する
4. ChatGPTからJSON配列を受け取る

ChatGPTに返してもらう形式は、説明文なしのJSON配列のみです。

例：

```json
[
  {
    "jp_title": "",
    "authors": "",
    "affiliations": "",
    "journal_doi": "",
    "en_title": "",
    "pubmed_info": "",
    "background": "",
    "methods": "",
    "results": "",
    "conclusion": ""
  }
]
```

---

### Step 5. `papers.json` に保存する

VS Codeで `papers.json` を開き、ChatGPTから返ってきたJSONを貼り付けます。

注意：

- 先頭は `[` にする
- 最後は `]` にする
- `以下がJSONです` などの説明文は入れない
- ```json のようなMarkdown記号は入れない
- 保存は `Ctrl + S`

---

### Step 6. PowerPointを生成する

PowerPointで `template.pptx` や `output.pptx` を開いている場合は閉じます。

その後、VS Codeのターミナルで実行します。

```powershell
python make_paper_slides_powerpoint.py template.pptx papers.json output.pptx
```

成功すると、同じフォルダに `output.pptx` ができます。

---

### Step 7. `output.pptx` を確認する

PowerPointで `output.pptx` を開いて確認します。

見るポイント：

- 論文ごとに4枚ずつ作成されているか
- `template.pptx` のデザインが反映されているか
- `{{jp_title}}` などのプレースホルダーが残っていないか
- 著者・所属がはみ出していないか
- `warnings` があった論文の所属情報が問題ないか

プレースホルダーが残っていないか確認するには、PowerPointで `Ctrl + F` を押して、以下を検索します。

```text
{{
```

見つからなければOKです。

---

## 3. 毎回使うコマンドまとめ

```powershell
python raw_to_input_papers_csv_v3.py input_raw.txt input_papers.csv
python pmid_pmcid_to_authors_affiliations.py input_papers.csv authors_affiliations.csv
python make_paper_slides_powerpoint.py template.pptx papers.json output.pptx
```

---

## 4. よくあるトラブル

### `Extracted records: 1` になってしまう

`input_raw.txt` の論文分割がうまくいっていません。

対処：

```text
論文1：
引用文

論文2：
引用文

論文3：
引用文
```

のように、論文ごとに `論文番号：` を付けてください。

---

### `output.pptx` が保存できない

PowerPointで `output.pptx` を開いたままの可能性があります。  
PowerPointを閉じてから再実行してください。

---

### デザインが崩れる

`make_paper_slides_powerpoint.py` を使ってください。  
これはPowerPoint本体にスライドをコピーさせる方式なので、`template.pptx` のデザインを再現しやすいです。

---

### 著者・所属が長すぎてはみ出す

まずはそのまま出力して、はみ出した論文だけ調整します。

対応例：

- テンプレート側のフォントサイズを小さくする
- affiliations欄を広げる
- 著者が極端に多い論文だけ `et al.` 表記にする

ただし、`authors` と `affiliations` はCSVの値を優先する運用なので、短縮する場合は別途ルール化してください。

---

## 5. 信頼性について

この運用では、著者・所属はChatGPTに推測させず、PubMed / PMC XMLから機械的に抽出します。

そのため、手作業で著者・所属を作るよりミスは減ります。

ただし、PubMed / PMC XMLに所属情報が入っていない論文では、所属が空欄になることがあります。  
その場合は `warnings` を確認し、必要に応じて出版社ページやPDFで確認してください。
