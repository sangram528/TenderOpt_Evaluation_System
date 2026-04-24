from scanner import scan_document

# This will return just the structured JSON you need
data = scan_document("tender 2.pdf")
print(data) # Just the features like Color, Dimensions, etc.