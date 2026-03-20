const countryList = [{'label': '留尼汪岛/Reunion, RN', 'value': 'REUNION'}, {
    'label': '美国本土外小岛屿/UNITED, UM',
    'value': 'UNITED'
}, {'label': '梵蒂冈/VATICAN, VA', 'value': 'VATICAN'}, {
    'label': '英属维尔京群岛/VIRGIN, VG',
    'value': 'VIRGIN'
}, {'label': '瓦利斯群岛和富图纳群岛/WALLIS, WF', 'value': 'WALLIS'}, {
    'label': '西萨摩亚/WESTERN, WS',
    'value': 'WESTERN'
}, {'label': '伯奈尔岛/BONAIRE, XB', 'value': 'BONAIRE'}, {
    'label': '库拉索岛(荷兰)/CURACAO, XC',
    'value': 'CURACAO'
}, {'label': '阿森松/ASCENSION, XD', 'value': 'ASCENSION'}, {
    'label': '圣尤斯塔提马斯岛/ST., XE',
    'value': 'ST.'
}, {'label': '北非西班牙属土/SPANISH, XG', 'value': 'SPANISH'}, {
    'label': '亚速尔群岛/AZORES, XH',
    'value': 'AZORES'
}, {'label': '马德拉岛/MADEIRA, XI', 'value': 'MADEIRA'}, {
    'label': '巴利阿里群岛/BALEARIC, XJ',
    'value': 'BALEARIC'
}, {'label': '加罗林群岛/CAROLINE, XK', 'value': 'CAROLINE'}, {
    'label': '圣马腾岛/ST., XM',
    'value': 'ST.'
}, {'label': '尼维斯岛/NEVIS, XN', 'value': 'NEVIS'}, {
    'label': '索马里共和国/SOMALILAND, XS',
    'value': 'SOMALILAND'
}, {'label': '圣巴特勒米岛/ST., XY', 'value': 'ST.'}, {
    'label': '马约特/MAYOTTE, YT',
    'value': 'MAYOTTE'
}, {'label': '扎伊尔/ZAIRE, ZR', 'value': 'ZAIRE'}, {
    'label': '荷属安的列斯群岛/NETHERLANDS, AN',
    'value': 'NETHERLANDS'
}, {'label': '波斯尼亚-黑塞哥维那共和国/BOSNIA, BA', 'value': 'BOSNIA'}, {
    'label': '布维岛/BOUVET, BV',
    'value': 'BOUVET'
}, {
    'label': '科科斯群岛/COCOS(KEELING)ISLANDS, CC',
    'value': 'COCOS(KEELING)ISLANDS'
}, {'label': '刚果民主共和国/CONGO, CD', 'value': 'CONGO'}, {
    'label': '科特迪瓦(象牙海岸)/COTE, CI',
    'value': 'COTE'
}, {'label': '中国/CHINA, CN', 'value': 'CHINA'}, {
    'label': '佛得角群岛/CAPE, CV',
    'value': 'CAPE'
}, {'label': '圣诞岛/CHRISTMAS, CX', 'value': 'CHRISTMAS'}, {
    'label': '西撒哈拉/WESTERN, EH',
    'value': 'WESTERN'
}, {'label': '密克罗尼西亚/MICRONESIA, FM', 'value': 'MICRONESIA'}, {
    'label': '法属美特罗波利坦/FRANCE,, FX',
    'value': 'FRANCE'
}, {'label': '根西岛/GUERNSEY, GG', 'value': 'GUERNSEY'}, {
    'label': '南乔治亚岛和南桑威奇群岛/SOUTH, GS',
    'value': 'SOUTH'
}, {'label': '赫德岛和麦克唐纳岛/HEARD, HM', 'value': 'HEARD'}, {
    'label': '加那利群岛/CANARY, IC',
    'value': 'CANARY'
}, {'label': '爱尔兰/IRELAND, IE', 'value': 'IRELAND'}, {
    'label': '英属印度洋地区(查各群岛)/BRITISH, IO',
    'value': 'BRITISH'
}, {'label': '圣基茨/SAINT, KN', 'value': 'SAINT'}, {
    'label': '朝鲜/NORTH, KP',
    'value': 'NORTH'
}, {'label': '科索沃/KOSOVO, KV', 'value': 'KOSOVO'}, {
    'label': '黑山共和国/MONTENEGRO, ME',
    'value': 'MONTENEGRO'
}, {'label': '塞班岛/SAIPAN, MP', 'value': 'SAIPAN'}, {
    'label': '马提尼克岛/MARTINIQUE, MQ',
    'value': 'MARTINIQUE'
}, {'label': '塔希堤岛(法属波利尼西亚)/FRENCH, PF', 'value': 'FRENCH'}, {
    'label': '圣皮埃尔和密克隆群岛/SAINT, PM',
    'value': 'SAINT'
}, {'label': '皮特凯恩群岛/PITCAIRN, PN', 'value': 'PITCAIRN'}, {
    'label': '帕劳/PALAU, PW',
    'value': 'PALAU'
}, {'label': '塞尔维亚共和国/SERBIA,, RS', 'value': 'SERBIA'}, {
    'label': '圣赫勒拿岛/ST, SH',
    'value': 'ST'
}, {'label': '斯瓦尔巴岛和扬马延岛/SVALBARD, SJ', 'value': 'SVALBARD'}, {
    'label': '特里斯坦/TRISTAN, TA',
    'value': 'TRISTAN'
}, {'label': '法属南部领土/FRENCH, TF', 'value': 'FRENCH'}, {
    'label': '托克劳/TOKELAU, TK',
    'value': 'TOKELAU'
}, {'label': '东帝汶/EAST, TL', 'value': 'EAST'}, {
    'label': '南斯拉夫/YUGOSLAVIA, JU',
    'value': 'YUGOSLAVIA'
}, {'label': '南苏丹共和国/SOUTH, SS', 'value': 'SOUTH'}, {
    'label': '巴勒斯坦/PALESTINE, PS',
    'value': 'PALESTINE'
}, {'label': '诺福克岛/nuofukedao, NF', 'value': 'NUOFUKEDAO'}, {
    'label': '萨巴/REWRWE, RE',
    'value': 'REWRWE'
}, {'label': '特克斯和凯科斯群岛/Turks, TC', 'value': 'TURKS'}, {
    'label': '澳门/Macau, MO',
    'value': 'MACAU'
}, {'label': '台湾/Taiwan, TW', 'value': 'TAIWAN'}, {
    'label': '香港/Hongkong, HK',
    'value': 'HONGKONG'
}, {'label': '新加坡/Singapore, SG', 'value': 'SINGAPORE'}, {
    'label': '阿尔巴尼亚/Albania, AL',
    'value': 'ALBANIA'
}, {'label': '阿尔及利亚/Algeria, DZ', 'value': 'ALGERIA'}, {
    'label': '阿富汗/Afghanistan, AF',
    'value': 'AFGHANISTAN'
}, {'label': '阿根廷/Argentina, AR', 'value': 'ARGENTINA'}, {
    'label': '阿联酋/United, AE',
    'value': 'EMIRATE'
}, {'label': '阿鲁巴/Aruba, AW', 'value': 'ARUBA'}, {
    'label': '阿曼/Oman, OM',
    'value': 'OMAN'
}, {'label': '阿塞拜疆/Azerbaijan, AZ', 'value': 'AZERBAIJAN'}, {
    'label': '埃及/Egypt, EG',
    'value': 'EGYPT'
}, {'label': '埃塞俄比亚/ETHIOPIA, ET', 'value': 'ETHIOPIA'}, {
    'label': '爱沙尼亚/Estonia, EE',
    'value': 'ESTONIA'
}, {'label': '安道尔/ANDORRA, AD', 'value': 'ANDORRA'}, {
    'label': '安哥拉/Angola, AO',
    'value': 'ANGOLA'
}, {'label': '安圭拉/Anguilla, AI', 'value': 'ANGUILLA'}, {
    'label': '安提瓜/ANTIGUA, AG',
    'value': 'ANTIGUA'
}, {'label': '奥地利/AUSTRIA, AT', 'value': 'AUSTRIA'}, {
    'label': '澳大利亚/Australia, AU',
    'value': 'AUSTRALIA'
}, {'label': '巴巴多斯/Barbados, BB', 'value': 'BARBADOS'}, {
    'label': '巴布亚新几内亚/Papua, PG',
    'value': 'PAPUA'
}, {'label': '巴哈马/BAHAMAS, BS', 'value': 'BAHAMAS'}, {
    'label': '巴基斯坦/Pakistan, PK',
    'value': 'PAKISTAN'
}, {'label': '巴拉圭/Paraguay, PY', 'value': 'PARAGUAY'}, {
    'label': '巴林/Bahrain, BH',
    'value': 'BAHRAIN'
}, {'label': '巴拿马/Panama, PA', 'value': 'PANAMA'}, {
    'label': '巴西/Brazil, BR',
    'value': 'BRAZIL'
}, {'label': '白俄罗斯/Belarus, BY', 'value': 'BELARUS'}, {
    'label': '百慕大/Bermuda, BM',
    'value': 'BERMUDA'
}, {'label': '保加利亚/Bulgaria, BG', 'value': 'BULGARIA'}, {
    'label': '贝宁/Benin, BJ',
    'value': 'BENIN'
}, {'label': '比利时/BELGIUM, BE', 'value': 'BELGIUM'}, {
    'label': '冰岛/Iceland, IS',
    'value': 'ICELAND'
}, {'label': '波利维亚/BOLIVIA, BO', 'value': 'BOLIVIA'}, {
    'label': '波多黎各/Puerto, PR',
    'value': 'PUERTO'
}, {'label': '波兰/POLAND, PL', 'value': 'POLAND'}, {
    'label': '博茨瓦纳/Botswana, BW',
    'value': 'BOTSWANA'
}, {'label': '伯利兹/Belize, BZ', 'value': 'BELIZE'}, {
    'label': '不丹/Bhutan, BT',
    'value': 'BHUTAN'
}, {'label': '布基纳法索/Burkina, BF', 'value': 'BURKINA'}, {
    'label': '布隆迪/Burundi, BI',
    'value': 'BURUNDI'
}, {'label': '赤道几内亚/Equatorial, GQ', 'value': 'EQUATORIAL'}, {
    'label': '丹麦/Denmark, DK',
    'value': 'DENMARK'
}, {'label': '德国/Germany, DE', 'value': 'GERMANY'}, {
    'label': '多哥/Togo, TG',
    'value': 'TOGO'
}, {'label': '多米尼加/Dominica, DM', 'value': 'DOMINICA'}, {
    'label': '多米尼加共和国/Dominican, DO',
    'value': 'DOMINICAN'
}, {'label': '俄罗斯/RUSSIAN, RU', 'value': 'RUSSIAN'}, {
    'label': '厄瓜多尔/Ecuador, EC',
    'value': 'ECUADOR'
}, {'label': '厄立特里亚/Eritrea, ER', 'value': 'ERITREA'}, {
    'label': '法国/France, FR',
    'value': 'FRANCE'
}, {'label': '法罗群岛/Faroe, FO', 'value': 'FAROE'}, {
    'label': '法属圭亚那/French, GF',
    'value': 'FRENCH'
}, {'label': '菲律宾/Philippines, PH', 'value': 'PHILIPPINES'}, {
    'label': '芬兰/Finland, FI',
    'value': 'FINLAND'
}, {'label': '福克兰群岛/Falkland, FK', 'value': 'FALKLAND'}, {
    'label': '冈比亚/Gambia, GM',
    'value': 'GAMBIA'
}, {'label': '刚果/CONGO, CG', 'value': 'CONGO'}, {
    'label': '哥伦比亚/Colombia, CO',
    'value': 'COLOMBIA'
}, {'label': '哥斯达黎加/COSTA, CR', 'value': 'COSTA'}, {
    'label': '格林纳达/Grenada, GD',
    'value': 'GRENADA'
}, {'label': '格陵兰岛/Greenland, GL', 'value': 'GREENLAND'}, {
    'label': '格鲁吉亚/Georgia, GE',
    'value': 'GEORGIA'
}, {'label': '古巴/CUBA, CU', 'value': 'CUBA'}, {
    'label': '瓜德罗普/Guadeloupe, GP',
    'value': 'GUADELOUPE'
}, {'label': '关岛/Guam, GU', 'value': 'GUAM'}, {
    'label': '圭亚那/Guyana(British), GY',
    'value': 'GUYANA(BRITISH)'
}, {'label': '哈萨克斯坦/Kazakhstan, KZ', 'value': 'KAZAKHSTAN'}, {
    'label': '海地/Haiti, HT',
    'value': 'HAITI'
}, {'label': '韩国/Korea, KR', 'value': 'KOREA'}, {
    'label': '荷兰/NETHERLANDS, NL',
    'value': 'NETHERLANDS'
}, {'label': '洪都拉斯/Honduras, HN', 'value': 'HONDURAS'}, {
    'label': '基里巴斯/Kiribati, KI',
    'value': 'KIRIBATI'
}, {'label': '吉布提/Djibouti, DJ', 'value': 'DJIBOUTI'}, {
    'label': '吉尔吉斯斯坦/Kyrgyzstan, KG',
    'value': 'KYRGYZSTAN'
}, {'label': '几内亚/Guinea, GN', 'value': 'GUINEA'}, {
    'label': '几内亚比绍/GUINEA, GW',
    'value': 'GUINEA'
}, {'label': '加拿大/Canada, CA', 'value': 'CANADA'}, {
    'label': '加纳/Ghana, GH',
    'value': 'GHANA'
}, {'label': '加蓬/Gabon, GA', 'value': 'GABON'}, {
    'label': '柬埔寨/Cambodia, KH',
    'value': 'CAMBODIA'
}, {'label': '捷克共和国/Czech, CZ', 'value': 'CZECH'}, {
    'label': '津巴布韦/Zimbabwe, ZW',
    'value': 'ZIMBABWE'
}, {'label': '喀麦隆/Cameroon, CM', 'value': 'CAMEROON'}, {
    'label': '卡塔尔/Qatar, QA',
    'value': 'QATAR'
}, {'label': '开曼群岛/Cayman, KY', 'value': 'CAYMAN'}, {
    'label': '科摩罗/Comoros, KM',
    'value': 'COMOROS'
}, {'label': '科威特/Kuwait, KW', 'value': 'KUWAIT'}, {
    'label': '克罗地亚/Croatia, HR',
    'value': 'CROATIA'
}, {'label': '肯尼亚/Kenya, KE', 'value': 'KENYA'}, {
    'label': '库克群岛/Cook, CK',
    'value': 'COOK'
}, {'label': '拉脱维亚/Latvia, LV', 'value': 'LATVIA'}, {
    'label': '莱索托/Lesotho, LS',
    'value': 'LESOTHO'
}, {'label': '老挝/Laos, LA', 'value': 'LAOS'}, {
    'label': '黎巴嫩/Lebanon, LB',
    'value': 'LEBANON'
}, {'label': '利比里亚/Liberia, LR', 'value': 'LIBERIA'}, {
    'label': '利比亚/Libya, LY',
    'value': 'LIBYA'
}, {'label': '立陶宛/Lithuania, LT', 'value': 'LITHUANIA'}, {
    'label': '列支敦士登/Liechtenstein, LI',
    'value': 'LIECHTENSTEIN'
}, {'label': '卢森堡/Luxembourg, LU', 'value': 'LUXEMBOURG'}, {
    'label': '卢旺达/Rwanda, RW',
    'value': 'RWANDA'
}, {'label': '罗马尼亚/Romania, RO', 'value': 'ROMANIA'}, {
    'label': '马达加斯加/Madagascar, MG',
    'value': 'MADAGASCAR'
}, {'label': '马耳他/MALTA, MT', 'value': 'MALTA'}, {
    'label': '马尔代夫/Maldives, MV',
    'value': 'MALDIVES'
}, {'label': '马拉维/Malawi, MW', 'value': 'MALAWI'}, {
    'label': '马来西亚/MALAYSIA, MY',
    'value': 'MALAYSIA'
}, {'label': '马里/MALI, ML', 'value': 'MALI'}, {
    'label': '马其顿/Macedonia, MK',
    'value': 'MACEDONIA'
}, {'label': '马绍尔群岛/Republic, MH', 'value': 'REPUBLIC'}, {
    'label': '毛里求斯/Mauritius, MU',
    'value': 'MAURITIUS'
}, {'label': '毛里塔尼亚/Mauritania, MR', 'value': 'MAURITANIA'}, {
    'label': '美国/UNITED, US',
    'value': 'USA'
}, {'label': '美属萨摩亚群岛/AMERICAN, AS', 'value': 'AMERICAN'}, {
    'label': '美属维尔京群岛/Virgin, VI',
    'value': 'VIRGIN'
}, {'label': '蒙古/Mongolia, MN', 'value': 'MONGOLIA'}, {
    'label': '蒙特塞拉岛/MONTSERRAT, MS',
    'value': 'MONTSERRAT'
}, {'label': '孟加拉/Bangladesh, BD', 'value': 'BANGLADESH'}, {
    'label': '秘鲁/Peru, PE',
    'value': 'PERU'
}, {'label': '缅甸/Myanmar, MM', 'value': 'MYANMAR'}, {
    'label': '摩尔多瓦/MOLDOVA,, MD',
    'value': 'MOLDOVA'
}, {'label': '摩洛哥/Morocco, MA', 'value': 'MOROCCO'}, {
    'label': '摩纳哥/MONACO, MC',
    'value': 'MONACO'
}, {'label': '莫桑比克/Mozambique, MZ', 'value': 'MOZAMBIQUE'}, {
    'label': '墨西哥/Mexico, MX',
    'value': 'MEXICO'
}, {'label': '纳米比亚/Namibia, NA', 'value': 'NAMIBIA'}, {
    'label': '南非/South, ZA',
    'value': 'SOUTH'
}, {'label': '尼泊尔/Nepal, NP', 'value': 'NEPAL'}, {
    'label': '尼加拉瓜/Nicaragua, NI',
    'value': 'NICARAGUA'
}, {'label': '尼日尔/Niger, NE', 'value': 'NIGER'}, {
    'label': '尼日利亚/Nigeria, NG',
    'value': 'NIGERIA'
}, {'label': '纽埃岛/Niue, NU', 'value': 'NIUE'}, {
    'label': '挪威/Norway, NO',
    'value': 'NORWAY'
}, {'label': '葡萄牙/Portugal, PT', 'value': 'PORTUGAL'}, {
    'label': '日本/Japan, JP',
    'value': 'JAPAN'
}, {'label': '瑞典/SWEDEN, SE', 'value': 'SWEDEN'}, {
    'label': '瑞士/Switzerland, CH',
    'value': 'SWITZERLAND'
}, {'label': '萨尔瓦多/El, SV', 'value': 'EL'}, {
    'label': '圣马力诺/SAN, SM',
    'value': 'SAN'
}, {'label': '塞拉利昂/Sierra, SL', 'value': 'SIERRA'}, {
    'label': '塞内加尔/Senegal, SN',
    'value': 'SENEGAL'
}, {'label': '塞浦路斯/Cyprus, CY', 'value': 'CYPRUS'}, {
    'label': '塞舌尔/Seychelles, SC',
    'value': 'SEYCHELLES'
}, {'label': '沙特阿拉伯/SAUDI, SA', 'value': 'SAUDI'}, {
    'label': '圣多美和普林西比/SAO, ST',
    'value': 'SAO'
}, {'label': '圣卢西亚岛/St, LC', 'value': 'ST'}, {
    'label': '圣文森特岛/St, VC',
    'value': 'ST'
}, {'label': '斯里兰卡/Sri, LK', 'value': 'SRI'}, {
    'label': '斯洛伐克/SLOVAKIA, SK',
    'value': 'SLOVAKIA'
}, {'label': '斯洛文尼亚/Slovenia, SI', 'value': 'SLOVENIA'}, {
    'label': '斯威士兰/Swaziland, SZ',
    'value': 'SWAZILAND'
}, {'label': '苏丹/Sudan, SD', 'value': 'SUDAN'}, {
    'label': '苏里南/Suriname, SR',
    'value': 'SURINAME'
}, {'label': '索马里/Somalia, SO', 'value': 'SOMALIA'}, {
    'label': '所罗门群岛/SOLOMON, SB',
    'value': 'SOLOMON'
}, {'label': '塔吉克斯坦/Tajikistan, TJ', 'value': 'TAJIKISTAN'}, {
    'label': '泰国/THAILAND, TH',
    'value': 'THAILAND'
}, {'label': '坦桑尼亚/Tanzania, TZ', 'value': 'TANZANIA'}, {
    'label': '汤加/Tonga, TO',
    'value': 'TONGA'
}, {'label': '特立尼达和多巴哥/Trinidad, TT', 'value': 'TRINIDAD'}, {
    'label': '突尼斯/Tunisia, TN',
    'value': 'TUNISIA'
}, {'label': '图瓦卢/Tuvalu, TV', 'value': 'TUVALU'}, {
    'label': '土耳其/Turkey, TR',
    'value': 'TURKEY'
}, {'label': '土库曼斯坦/Turkmenistan, TM', 'value': 'TURKMENISTAN'}, {
    'label': '瓦努阿图/Vanuatu, VU',
    'value': 'VANUATU'
}, {'label': '危地马拉/Guatemala, GT', 'value': 'GUATEMALA'}, {
    'label': '委内瑞拉/Venezuela, VE',
    'value': 'VENEZUELA'
}, {'label': '文莱/BRUNEI, BN', 'value': 'BRUNEI'}, {
    'label': '乌干达/Uganda, UG',
    'value': 'UGANDA'
}, {'label': '乌克兰/UKRAINE, UA', 'value': 'UKRAINE'}, {
    'label': '乌拉圭/Uruguay, UY',
    'value': 'URUGUAY'
}, {'label': '乌兹别克斯坦/Uzbekistan, UZ', 'value': 'UZBEKISTAN'}, {
    'label': '西班牙/Spain, ES',
    'value': 'SPAIN'
}, {'label': '希腊/Greece, GR', 'value': 'GREECE'}, {
    'label': '新喀里多尼亚/New, NC',
    'value': 'NEW'
}, {'label': '新西兰/New, NZ', 'value': 'NEW'}, {
    'label': '匈牙利/Hungary, HU',
    'value': 'HUNGARY'
}, {'label': '叙利亚/Syria, SY', 'value': 'SYRIA'}, {
    'label': '牙买加/Jamaica, JM',
    'value': 'JAMAICA'
}, {'label': '亚美尼亚/Armenia, AM', 'value': 'ARMENIA'}, {
    'label': '也门/Yemen, YE',
    'value': 'YEMEN'
}, {'label': '伊拉克/Iraq, IQ', 'value': 'IRAQ'}, {
    'label': '伊朗/Iran, IR',
    'value': 'IRAN'
}, {'label': '以色列/Israel, IL', 'value': 'ISRAEL'}, {
    'label': '意大利/Italy, IT',
    'value': 'ITALY'
}, {'label': '印度/India, IN', 'value': 'INDIA'}, {
    'label': '印度尼西亚/Indonesia, ID',
    'value': 'INDONESIA'
}, {'label': '英国/UNITED, GB', 'value': 'UK'}, {
    'label': '约旦/Jordan, JO',
    'value': 'JORDAN'
}, {'label': '越南/VIETNAM, VN', 'value': 'VIETNAM'}, {
    'label': '赞比亚/Zambia, ZM',
    'value': 'ZAMBIA'
}, {'label': '泽西岛/Jersey, JE', 'value': 'JERSEY'}, {
    'label': '乍得/Chad, TD',
    'value': 'CHAD'
}, {'label': '直布罗陀/Gibraltar, GI', 'value': 'GIBRALTAR'}, {
    'label': '智利/Chile, CL',
    'value': 'CHILE'
}, {'label': '中非共和国/Central, CF', 'value': 'CENTRAL'}, {
    'label': '瑙鲁/Nauru,, NR',
    'value': 'NAURU'
}, {'label': '斐济群岛/Fiji, FJ', 'value': 'FIJI'}]
export default countryList;